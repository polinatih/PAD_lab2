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
