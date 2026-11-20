from datetime import date, datetime, timedelta, timezone

from conftest import ADMIN, CUSTOMER, DECLINED, GOOD, OTHER, order_created, wait_events
from sqlalchemy import update

from app.gateway import luhn_ok, validate_card
from app.models import Payment


def test_card_validation():
    assert luhn_ok("4242424242424242") and not luhn_ok("4242424242424241")
    assert validate_card("4242424242424242", 12, 30, "123", today=date(2026, 11, 20)) == []
    errors = validate_card("1234", 1, 20, "1", today=date(2026, 11, 20))
    assert {e["field"] for e in errors} == {"card_number", "expiry", "cvc"}


def test_payment_created_from_event_and_paid(client, bus):
    order_created(client, bus)
    order_created(client, bus)  # повторная доставка не создаёт второй платёж
    p = client.get("/api/payments/order/o1", headers=CUSTOMER).json()
    assert p["status"] == "pending" and p["amount"] == 318.0 and p["attempts_left"] == 3

    r = client.post("/api/payments/order/o1/pay", json=GOOD, headers=CUSTOMER)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded" and r.json()["card_last4"] == "4242" and r.json()["card_brand"] == "Visa"
    assert wait_events(bus, 1) == ["payment.succeeded"]
    assert bus.published[0]["data"]["order_id"] == "o1"

    r = client.post("/api/payments/order/o1/pay", json=GOOD, headers=CUSTOMER)
    assert r.status_code == 409 and r.json()["error"]["code"] == "payment_closed"


def test_not_ready_and_foreign(client, bus):
    r = client.get("/api/payments/order/o1", headers=CUSTOMER)
    assert r.status_code == 404 and r.json()["error"]["code"] == "payment_not_ready"
    order_created(client, bus)
    assert client.get("/api/payments/order/o1", headers=OTHER).status_code == 404
    assert client.get("/api/payments/order/o1", headers=ADMIN).status_code == 200


def test_invalid_card(client, bus):
    order_created(client, bus)
    r = client.post("/api/payments/order/o1/pay", json=GOOD | {"card_number": "4242 4242 4242 4241"}, headers=CUSTOMER)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_card"
    assert client.get("/api/payments/order/o1", headers=CUSTOMER).json()["attempts"] == 0  # не считается попыткой


def test_three_declines_fail_the_payment(client, bus):
    order_created(client, bus)
    for left in (2, 1):
        r = client.post("/api/payments/order/o1/pay", json=DECLINED, headers=CUSTOMER)
        assert r.status_code == 402 and r.json()["error"]["details"]["attempts_left"] == left
    r = client.post("/api/payments/order/o1/pay", json=DECLINED, headers=CUSTOMER)
    assert r.status_code == 402 and r.json()["error"]["code"] == "payment_failed"
    assert wait_events(bus, 1) == ["payment.failed"]
    p = client.get("/api/payments/order/o1", headers=CUSTOMER).json()
    assert p["status"] == "failed" and len(p["transactions"]) == 3


def test_expired_payment_fails(client, app, bus):
    order_created(client, bus)

    async def make_overdue():
        async with app.state.db.sessionmaker() as s:
            await s.execute(update(Payment).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await s.commit()
        return await app.state.handlers.expire_overdue()

    assert client.portal.call(make_overdue) == 1
    assert wait_events(bus, 1) == ["payment.failed"]
    assert bus.published[0]["data"]["reason"] == "Время на оплату истекло"
    assert client.get("/api/payments/order/o1", headers=CUSTOMER).json()["status"] == "expired"


def test_refund_on_cancel(client, bus):
    order_created(client, bus)
    client.post("/api/payments/order/o1/pay", json=GOOD, headers=CUSTOMER)
    client.portal.call(bus.deliver, "order.cancelled", {"order_id": "o1", "reason": "Ресторан закрылся", "refund": True})
    assert wait_events(bus, 2) == ["payment.succeeded", "payment.refunded"]
    p = client.get("/api/payments/order/o1", headers=CUSTOMER).json()
    assert p["status"] == "refunded" and [t["kind"] for t in p["transactions"]] == ["charge", "refund"]


def test_cancel_before_payment(client, bus):
    order_created(client, bus)
    client.portal.call(bus.deliver, "order.cancelled", {"order_id": "o1", "refund": False})
    assert client.get("/api/payments/order/o1", headers=CUSTOMER).json()["status"] == "cancelled"
    assert client.post("/api/payments/order/o1/pay", json=GOOD, headers=CUSTOMER).status_code == 409
