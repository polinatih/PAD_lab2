from conftest import COURIER, CUSTOMER, ORDER, OWNER

from common.messaging import make_envelope


def deliver(client, bus, event_type, data):
    client.portal.call(bus.deliver, event_type, data)


def titles(client, h):
    return [n["title"] for n in client.get("/api/notifications", headers=h).json()]


def test_order_lifecycle_notifies_the_right_people(client, bus):
    deliver(client, bus, "order.created", ORDER)
    deliver(client, bus, "order.paid", ORDER)
    deliver(client, bus, "delivery.assigned", {"order_id": "o1", "order_number": "AB12CD", "customer_id": "cust",
                                               "courier_id": "andrei", "courier_name": "Андрей", "courier_phone": "+37379"})
    deliver(client, bus, "delivery.delivered", {"order_id": "o1", "order_number": "AB12CD", "customer_id": "cust",
                                                "courier_id": "andrei", "courier_fee": 25.0})

    assert titles(client, CUSTOMER) == ["Курьер назначен", "Заказ № AB12CD оплачен", "Заказ № AB12CD оформлен"]
    assert titles(client, OWNER) == ["Новый заказ № AB12CD"]
    courier = client.get("/api/notifications", headers=COURIER).json()
    assert courier[0]["body"] == "Заработок: 25 лей." and courier[0]["link"] == "#/courier/history"
    assert client.get("/api/notifications/unread-count", headers=CUSTOMER).json() == {"unread": 3}


def test_cancel_after_payment_notifies_restaurant_and_mentions_refund(client, bus):
    deliver(client, bus, "order.cancelled", ORDER | {"reason": "Передумала", "refund": True, "cancelled_by": "клиент",
                                                     "previous_status": "paid"})
    customer = client.get("/api/notifications", headers=CUSTOMER).json()[0]
    assert customer["level"] == "error" and "Деньги вернутся на карту" in customer["body"]
    assert titles(client, OWNER) == ["Заказ № AB12CD отменён"]

    # отмена до оплаты ресторану не интересна
    deliver(client, bus, "order.cancelled", ORDER | {"order_id": "o2", "previous_status": "pending_payment"})
    assert len(titles(client, OWNER)) == 1


def test_duplicate_event_creates_one_notification(client, bus):
    env = make_envelope("order.created", ORDER, "test")
    handler = bus.handlers["order.created"]
    client.portal.call(handler, env)
    client.portal.call(handler, env)
    assert len(titles(client, CUSTOMER)) == 1


def test_read_flow_and_privacy(client, bus):
    deliver(client, bus, "order.created", ORDER)
    deliver(client, bus, "order.accepted", ORDER)
    first = client.get("/api/notifications", headers=CUSTOMER).json()[0]["id"]
    assert client.post(f"/api/notifications/{first}/read", headers=OWNER).status_code == 404
    assert client.post(f"/api/notifications/{first}/read", headers=CUSTOMER).json()["is_read"] is True
    assert len(client.get("/api/notifications", params={"unread_only": True}, headers=CUSTOMER).json()) == 1
    assert client.post("/api/notifications/read-all", headers=CUSTOMER).json() == {"updated": 1}
    assert client.get("/api/notifications/unread-count", headers=CUSTOMER).json() == {"unread": 0}
    assert client.get("/api/notifications").status_code == 401


def test_unknown_event_is_ignored(client, bus):
    bus.handlers["something.else"] = bus.handlers["order.created"]
    deliver(client, bus, "something.else", {"x": 1})
    assert titles(client, CUSTOMER) == []
