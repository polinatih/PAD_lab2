import pytest
from conftest import ADMIN, CUSTOMER, ORDER, OTHER, OWNER, headers, wait_events

from app import states
from common.errors import Conflict


def test_create_order_uses_restaurant_prices(client, bus):
    # клиент «подсовывает» свою цену — она игнорируется, цены считает restaurant-service
    body = ORDER | {"items": [{"menu_item_id": "m1", "quantity": 2, "price": 1}, {"menu_item_id": "m2", "quantity": 1}]}
    r = client.post("/api/orders", json=body, headers=CUSTOMER)
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["status"] == "pending_payment" and order["status_label"] == "Ожидает оплаты"
    assert (order["subtotal"], order["delivery_fee"], order["total"]) == (293.0, 25.0, 318.0)
    assert order["customer_name"] == "Мария" and order["customer_phone"] == "+37369000000"
    assert [h["status"] for h in order["history"]] == ["pending_payment"]
    assert len(order["number"]) == 6

    assert wait_events(bus, 1) == ["order.created"]
    data = bus.published[0]["data"]
    assert data["order_id"] == order["id"] and data["total"] == 318.0 and data["restaurant_owner_id"] == "owner"


def test_only_customers_order(client):
    assert client.post("/api/orders", json=ORDER, headers=OWNER).status_code == 403
    assert client.post("/api/orders", json=ORDER).status_code == 401
    assert client.post("/api/orders", json=ORDER | {"items": []}, headers=CUSTOMER).status_code == 422


def test_idempotency_key(client, neighbors):
    h = CUSTOMER | {"Idempotency-Key": "click-1"}
    first = client.post("/api/orders", json=ORDER, headers=h)
    second = client.post("/api/orders", json=ORDER, headers=h)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert neighbors.quotes == 1
    assert len(client.get("/api/orders", headers=CUSTOMER).json()) == 1


def test_restaurant_errors_are_passed_through(client, neighbors):
    neighbors.restaurant_mode = "closed"
    r = client.post("/api/orders", json=ORDER, headers=CUSTOMER)
    assert r.status_code == 409 and r.json()["error"]["message"] == "Ресторан закрыт"

    neighbors.restaurant_mode = "down"
    r = client.post("/api/orders", json=ORDER, headers=CUSTOMER)
    assert r.status_code == 503 and r.json()["error"]["code"] == "service_unavailable"


def test_order_works_when_auth_service_is_down(client, neighbors):
    neighbors.auth_mode = "down"
    r = client.post("/api/orders", json=ORDER, headers=CUSTOMER)
    assert r.status_code == 400 and r.json()["error"]["code"] == "phone_required"
    r = client.post("/api/orders", json=ORDER | {"phone": "+373 79 111 111"}, headers=CUSTOMER)
    assert r.status_code == 201 and r.json()["customer_phone"] == "+373 79 111 111"


def test_visibility(client):
    oid = client.post("/api/orders", json=ORDER, headers=CUSTOMER).json()["id"]
    assert client.get(f"/api/orders/{oid}", headers=CUSTOMER).status_code == 200
    assert client.get(f"/api/orders/{oid}", headers=OWNER).status_code == 200      # ресторан видит свои заказы
    assert client.get(f"/api/orders/{oid}", headers=OTHER).status_code == 404      # чужой клиент — нет
    assert client.get(f"/api/orders/{oid}", headers=headers("o2", "restaurant")).status_code == 404
    assert client.get(f"/api/orders/{oid}", headers=ADMIN).status_code == 200
    assert len(client.get("/api/orders", headers=OWNER).json()) == 1
    assert client.get("/api/orders", headers=OTHER).json() == []
    assert client.get(f"/internal/orders/{oid}", headers={"X-Internal-Key": "ik"}).status_code == 200


def test_customer_cancels(client, bus):
    oid = client.post("/api/orders", json=ORDER, headers=CUSTOMER).json()["id"]
    assert client.post(f"/api/orders/{oid}/cancel", json={"reason": "x"}, headers=OTHER).status_code == 404
    r = client.post(f"/api/orders/{oid}/cancel", json={"reason": "Передумала"}, headers=CUSTOMER)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled" and body["cancel_reason"] == "Передумала"
    assert [h["status"] for h in body["history"]] == ["pending_payment", "cancelled"]
    assert wait_events(bus, 2) == ["order.created", "order.cancelled"]
    assert bus.published[1]["data"]["refund"] is False  # не был оплачен — возвращать нечего

    r = client.post(f"/api/orders/{oid}/cancel", headers=CUSTOMER)
    assert r.status_code == 409 and r.json()["error"]["code"] == "cannot_cancel"
    assert client.get("/api/orders", params={"active": True}, headers=CUSTOMER).json() == []
    assert len(client.get("/api/orders", params={"status": "cancelled"}, headers=CUSTOMER).json()) == 1


def test_state_machine():
    assert states.can_transition(states.PENDING_PAYMENT, states.PAID)
    assert states.can_transition(states.IN_DELIVERY, states.DELIVERED)
    assert not states.can_transition(states.DELIVERED, states.COOKING)
    assert not states.can_transition(states.PENDING_PAYMENT, states.COOKING)  # нельзя готовить неоплаченный
    with pytest.raises(Conflict):
        states.ensure_transition(states.CANCELLED, states.PAID)


def _paid_order(client, bus):
    oid = client.post("/api/orders", json=ORDER, headers=CUSTOMER).json()["id"]
    client.portal.call(bus.deliver, "payment.succeeded", {"order_id": oid, "card_brand": "Visa", "card_last4": "4242"})
    return oid


def test_saga_payment_succeeded_then_kitchen(client, bus):
    oid = _paid_order(client, bus)
    order = client.get(f"/api/orders/{oid}", headers=CUSTOMER).json()
    assert order["status"] == "paid" and order["history"][-1]["note"] == "Оплачено: Visa •• 4242"
    # повторная доставка того же события ничего не меняет
    client.portal.call(bus.deliver, "payment.succeeded", {"order_id": oid})
    assert len(client.get(f"/api/orders/{oid}", headers=CUSTOMER).json()["history"]) == 2

    assert client.post(f"/api/orders/{oid}/accept", headers=CUSTOMER).status_code == 403
    assert client.post(f"/api/orders/{oid}/ready", headers=OWNER).status_code == 409  # сначала нужно принять
    assert client.post(f"/api/orders/{oid}/accept", headers=OWNER).json()["status"] == "cooking"
    assert client.post(f"/api/orders/{oid}/cancel", headers=CUSTOMER).status_code == 409  # уже готовят
    ready = client.post(f"/api/orders/{oid}/ready", headers=OWNER).json()
    assert ready["status"] == "ready"
    types = wait_events(bus, 4)
    assert types == ["order.created", "order.paid", "order.accepted", "order.ready"]
    assert bus.published[3]["data"]["delivery_address"] == ORDER["delivery_address"]


def test_saga_payment_failed_cancels_order(client, bus):
    oid = client.post("/api/orders", json=ORDER, headers=CUSTOMER).json()["id"]
    client.portal.call(bus.deliver, "payment.failed", {"order_id": oid, "reason": "Время на оплату истекло"})
    order = client.get(f"/api/orders/{oid}", headers=CUSTOMER).json()
    assert order["status"] == "cancelled" and order["cancel_reason"] == "Время на оплату истекло"
    assert wait_events(bus, 2)[-1] == "order.cancelled"
    assert bus.published[-1]["data"]["refund"] is False
    # оплата, пришедшая после отмены, заказ не «воскрешает»
    client.portal.call(bus.deliver, "payment.succeeded", {"order_id": oid})
    assert client.get(f"/api/orders/{oid}", headers=CUSTOMER).json()["status"] == "cancelled"


def test_restaurant_rejects_paid_order_with_refund(client, bus):
    oid = _paid_order(client, bus)
    r = client.post(f"/api/orders/{oid}/cancel", json={"reason": "Закончилось тесто"}, headers=OWNER)
    assert r.status_code == 200 and r.json()["cancel_reason"] == "Закончилось тесто"
    assert wait_events(bus, 3)[-1] == "order.cancelled"
    assert bus.published[-1]["data"]["refund"] is True and bus.published[-1]["data"]["cancelled_by"] == "ресторан"


def test_delivery_events_complete_the_order(client, bus):
    oid = _paid_order(client, bus)
    client.post(f"/api/orders/{oid}/accept", headers=OWNER)
    client.post(f"/api/orders/{oid}/ready", headers=OWNER)
    courier = {"order_id": oid, "courier_id": "andrei", "courier_name": "Андрей", "courier_phone": "+37379333444"}
    client.portal.call(bus.deliver, "delivery.assigned", courier)
    order = client.get(f"/api/orders/{oid}", headers=CUSTOMER).json()
    assert order["status"] == "courier_assigned" and order["courier_phone"] == "+37379333444"
    # курьер теперь видит заказ
    assert client.get(f"/api/orders/{oid}", headers=headers("andrei", "courier")).status_code == 200

    client.portal.call(bus.deliver, "delivery.delivered", courier)  # пришло раньше времени — пропускаем
    assert client.get(f"/api/orders/{oid}", headers=CUSTOMER).json()["status"] == "courier_assigned"
    client.portal.call(bus.deliver, "delivery.picked_up", courier)
    client.portal.call(bus.deliver, "delivery.delivered", courier)
    order = client.get(f"/api/orders/{oid}", headers=CUSTOMER).json()
    assert order["status"] == "delivered"
    assert [h["status"] for h in order["history"]] == ["pending_payment", "paid", "cooking", "ready",
                                                       "courier_assigned", "in_delivery", "delivered"]
    assert wait_events(bus, 5)[-1] == "order.delivered"
