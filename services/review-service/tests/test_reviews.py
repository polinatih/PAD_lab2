from conftest import CUSTOMER, OTHER, OWNER, delivered, wait_events

from app.api import short_name
from app.main import reconcile


def test_review_only_after_delivery(client, bus):
    r = client.post("/api/reviews", json={"order_id": "o1", "rating": 5}, headers=CUSTOMER)
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_delivered"
    assert client.get("/api/reviews/order/o1", headers=CUSTOMER).json() == {"can_review": False, "review": None}

    delivered(client, bus)
    assert client.get("/api/reviews/order/o1", headers=CUSTOMER).json()["can_review"] is True
    assert client.post("/api/reviews", json={"order_id": "o1", "rating": 5}, headers=OTHER).status_code == 403  # чужой заказ

    r = client.post("/api/reviews", json={"order_id": "o1", "rating": 4, "comment": "Вкусно, но долго"}, headers=CUSTOMER)
    assert r.status_code == 201 and r.json()["author"] == "Мария И."
    again = client.post("/api/reviews", json={"order_id": "o1", "rating": 1}, headers=CUSTOMER)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_reviewed"

    assert wait_events(bus, 1) == ["review.created"]
    data = bus.published[0]["data"]
    assert (data["rating_avg"], data["rating_count"], data["restaurant_owner_id"]) == (4.0, 1, "owner")


def test_stats_and_public_list(client, bus):
    for oid, rating in (("o1", 5), ("o2", 4), ("o3", 2)):
        delivered(client, bus, oid)
        client.post("/api/reviews", json={"order_id": oid, "rating": rating}, headers=CUSTOMER)
    body = client.get("/api/reviews/restaurant/r1").json()  # без токена
    assert body["stats"]["rating_count"] == 3 and body["stats"]["rating_avg"] == 3.67
    assert body["stats"]["distribution"] == {"1": 0, "2": 1, "3": 0, "4": 1, "5": 1}
    assert len(body["items"]) == 3
    assert client.post("/api/reviews", json={"order_id": "o9", "rating": 6}, headers=CUSTOMER).status_code == 422


def test_owner_reply(client, bus):
    delivered(client, bus)
    rid = client.post("/api/reviews", json={"order_id": "o1", "rating": 3}, headers=CUSTOMER).json()["id"]
    assert client.post(f"/api/reviews/{rid}/reply", json={"text": "Спасибо!"}, headers=CUSTOMER).status_code == 403
    r = client.post(f"/api/reviews/{rid}/reply", json={"text": "Спасибо, исправимся!"}, headers=OWNER)
    assert r.status_code == 200 and r.json()["reply"] == "Спасибо, исправимся!"
    assert len(client.get("/api/reviews/owner", headers=OWNER).json()) == 1


def test_reconcile_and_short_name(client, orders):
    orders.delivered = [{"id": "old", "number": "OLD", "customer_id": "cust", "restaurant_id": "r1",
                         "restaurant_owner_id": "owner", "restaurant_name": "Тесто", "customer_name": "Ион"}]
    client.portal.call(reconcile, client.app.state.db, orders)
    assert client.get("/api/reviews/order/old", headers=CUSTOMER).json()["can_review"] is True
    assert short_name("Ion") == "Ion" and short_name("a@b.c") == "Клиент" and short_name("") == "Клиент"
