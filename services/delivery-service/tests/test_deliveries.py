from conftest import ANDREI, CUSTOMER, IGOR, online, order_ready, wait_events


def test_order_ready_creates_delivery_once(client, bus):
    order_ready(client, bus)
    order_ready(client, bus)  # повторная доставка события
    rows = client.get("/api/deliveries/available", headers=ANDREI).json()
    assert len(rows) == 1 and rows[0]["status"] == "searching" and rows[0]["courier_fee"] == 25.0


def test_full_delivery_flow(client, bus):
    order_ready(client, bus)
    did = client.get("/api/deliveries/available", headers=ANDREI).json()[0]["id"]

    r = client.post(f"/api/deliveries/{did}/claim", headers=ANDREI)
    assert r.status_code == 409 and r.json()["error"]["code"] == "courier_offline"
    online(client, ANDREI)
    claimed = client.post(f"/api/deliveries/{did}/claim", headers=ANDREI).json()
    assert claimed["status"] == "assigned" and claimed["courier_name"] == "Курьер andrei"

    assert client.post(f"/api/deliveries/{did}/deliver", headers=ANDREI).status_code == 409  # сначала забрать
    assert client.post(f"/api/deliveries/{did}/pickup", headers=ANDREI).json()["status"] == "picked_up"
    assert client.post(f"/api/deliveries/{did}/deliver", headers=ANDREI).json()["status"] == "delivered"
    assert wait_events(bus, 3) == ["delivery.assigned", "delivery.picked_up", "delivery.delivered"]
    assert bus.published[0]["data"]["order_id"] == "o1" and bus.published[0]["data"]["courier_phone"] == "+37379000000"

    stats = client.get("/api/deliveries/couriers/me", headers=ANDREI).json()
    assert stats["delivered_today"] == 1 and stats["earned_today"] == 25.0
    assert client.get("/api/deliveries/order/o1", headers=CUSTOMER).json()["courier_name"] == "Курьер andrei"


def test_only_one_courier_gets_the_order(client, bus):
    order_ready(client, bus)
    did = client.get("/api/deliveries/available", headers=ANDREI).json()[0]["id"]
    online(client, ANDREI)
    online(client, IGOR)
    assert client.post(f"/api/deliveries/{did}/claim", headers=ANDREI).status_code == 200
    r = client.post(f"/api/deliveries/{did}/claim", headers=IGOR)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_taken"
    assert client.post(f"/api/deliveries/{did}/pickup", headers=IGOR).status_code == 404  # чужая доставка


def test_one_active_delivery_and_cannot_go_offline(client, bus):
    order_ready(client, bus, "o1")
    order_ready(client, bus, "o2")
    online(client, ANDREI)
    ids = [d["id"] for d in client.get("/api/deliveries/available", headers=ANDREI).json()]
    assert client.post(f"/api/deliveries/{ids[0]}/claim", headers=ANDREI).status_code == 200
    r = client.post(f"/api/deliveries/{ids[1]}/claim", headers=ANDREI)
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_active"
    r = client.put("/api/deliveries/couriers/me", json={"is_online": False}, headers=ANDREI)
    assert r.status_code == 409 and r.json()["error"]["code"] == "active_delivery"
    assert len(client.get("/api/deliveries/mine", params={"active": True}, headers=ANDREI).json()) == 1


def test_claim_works_when_auth_is_down(client, bus, auth_state):
    order_ready(client, bus)
    online(client, ANDREI)
    auth_state["down"] = True
    did = client.get("/api/deliveries/available", headers=ANDREI).json()[0]["id"]
    r = client.post(f"/api/deliveries/{did}/claim", headers=ANDREI)
    assert r.status_code == 200 and r.json()["courier_name"] == "andrei@t.io"


def test_only_couriers(client, bus):
    order_ready(client, bus)
    assert client.get("/api/deliveries/available", headers=CUSTOMER).status_code == 403
    assert client.get("/api/deliveries/order/o1", headers=IGOR).status_code == 404


def test_reconcile_adds_missed_ready_orders(client, bus, orders):
    from app.main import reconcile
    order_ready(client, bus, "o1")
    orders.ready = [
        {"id": "o1", "number": "O1", "customer_id": "c", "customer_name": "", "customer_phone": None,
         "restaurant_name": "Тесто", "restaurant_address": "a", "delivery_address": "b", "comment": "", "total": 1, "delivery_fee": 2},
        {"id": "o9", "number": "O9", "customer_id": "c", "customer_name": "Ион", "customer_phone": None,
         "restaurant_name": "Мцвади", "restaurant_address": "a", "delivery_address": "b", "comment": "", "total": 1, "delivery_fee": 30},
    ]
    client.portal.call(reconcile, client.app.state.db, orders)
    rows = client.get("/api/deliveries/available", headers=ANDREI).json()
    assert sorted(r["order_id"] for r in rows) == ["o1", "o9"]  # o1 не задвоился, o9 добавлен
