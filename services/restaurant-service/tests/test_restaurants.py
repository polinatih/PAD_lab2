from conftest import ADMIN, CUSTOMER, INTERNAL, OTHER_OWNER, OWNER


def test_only_restaurant_role_can_create(client):
    body = {"name": "Суши", "cuisine": "Суши", "address": "ул. Ленина, 1"}
    assert client.post("/api/restaurants", json=body, headers=CUSTOMER).status_code == 403
    assert client.post("/api/restaurants", json=body).status_code == 401
    assert client.post("/api/restaurants", json=body | {"delivery_fee": -5}, headers=OWNER).status_code == 422


def test_public_catalog_and_menu(client, restaurant):
    catalog = client.get("/api/restaurants").json()  # без токена
    assert [r["name"] for r in catalog] == ["Пиццерия «Тесто»"]
    detail = client.get(f"/api/restaurants/{restaurant['id']}").json()
    assert detail["delivery_fee"] == 25.0
    assert {m["name"]: m["price"] for m in detail["menu"]}["Пепперони"] == 149.5
    assert client.get("/api/restaurants/nope").status_code == 404


def test_search_and_filters(client, restaurant):
    client.post("/api/restaurants", json={"name": "Сушия", "cuisine": "Суши", "address": "пр. Штефана, 5"}, headers=OWNER)
    assert len(client.get("/api/restaurants", params={"q": "дровяной"}).json()) == 1
    assert [r["name"] for r in client.get("/api/restaurants", params={"cuisine": "Суши"}).json()] == ["Сушия"]
    client.patch(f"/api/restaurants/{restaurant['id']}", json={"is_open": False}, headers=OWNER)
    assert [r["name"] for r in client.get("/api/restaurants", params={"open_only": True}).json()] == ["Сушия"]
    present = client.get("/api/restaurants/cuisines").json()["present"]
    assert {p["cuisine"] for p in present} == {"Пицца", "Суши"}


def test_only_owner_manages(client, restaurant):
    rid, item = restaurant["id"], restaurant["items"]["Маргарита"]
    assert client.patch(f"/api/restaurants/{rid}", json={"name": "Чужая"}, headers=OTHER_OWNER).status_code == 403
    assert client.post(f"/api/restaurants/{rid}/menu", json={"name": "X1", "price": 1}, headers=OTHER_OWNER).status_code == 403
    r = client.patch(f"/api/restaurants/{rid}/menu/{item}", json={"price": 139, "is_available": False}, headers=OWNER)
    assert r.status_code == 200 and r.json()["price"] == 139.0 and r.json()["is_available"] is False
    assert client.patch(f"/api/restaurants/{rid}", json={"name": "Тесто 2"}, headers=ADMIN).status_code == 200
    assert client.delete(f"/api/restaurants/{rid}/menu/{item}", headers=OWNER).status_code == 204
    assert client.delete(f"/api/restaurants/{rid}/menu/{item}", headers=OWNER).status_code == 404
    assert [r["id"] for r in client.get("/api/restaurants/mine", headers=OWNER).json()] == [rid]
    assert client.get("/api/restaurants/mine", headers=OTHER_OWNER).json() == []


def test_quote_calculates_prices(client, restaurant):
    rid, items = restaurant["id"], restaurant["items"]
    body = {"items": [{"menu_item_id": items["Пепперони"], "quantity": 1},
                      {"menu_item_id": items["Лимонад"], "quantity": 2},
                      {"menu_item_id": items["Лимонад"], "quantity": 1}]}
    assert client.post(f"/internal/restaurants/{rid}/quote", json=body).status_code == 403  # без внутреннего ключа
    q = client.post(f"/internal/restaurants/{rid}/quote", json=body, headers=INTERNAL).json()
    assert q["subtotal"] == 254.5 and q["delivery_fee"] == 25.0 and q["total"] == 279.5
    assert {line["name"]: line["quantity"] for line in q["items"]} == {"Пепперони": 1, "Лимонад": 3}
    assert q["owner_id"] == "owner"


def test_quote_rejects_bad_orders(client, restaurant):
    rid, items = restaurant["id"], restaurant["items"]
    url = f"/internal/restaurants/{rid}/quote"

    r = client.post(url, json={"items": [{"menu_item_id": items["Лимонад"], "quantity": 1}]}, headers=INTERNAL)
    assert r.status_code == 400 and r.json()["error"]["code"] == "below_min_order"

    client.patch(f"/api/restaurants/{rid}/menu/{items['Маргарита']}", json={"is_available": False}, headers=OWNER)
    r = client.post(url, json={"items": [{"menu_item_id": items["Маргарита"], "quantity": 2},
                                         {"menu_item_id": "ghost", "quantity": 1}]}, headers=INTERNAL)
    assert r.status_code == 409 and r.json()["error"]["code"] == "items_unavailable"
    assert len(r.json()["error"]["details"]) == 2

    client.patch(f"/api/restaurants/{rid}", json={"is_open": False}, headers=OWNER)
    r = client.post(url, json={"items": [{"menu_item_id": items["Пепперони"], "quantity": 1}]}, headers=INTERNAL)
    assert r.status_code == 409 and r.json()["error"]["code"] == "restaurant_closed"


def test_rating_updated_from_review_event(client, restaurant, bus):
    client.portal.call(bus.deliver, "review.created", {"restaurant_id": restaurant["id"], "rating_avg": 4.5, "rating_count": 2})
    r = client.get(f"/api/restaurants/{restaurant['id']}").json()
    assert (r["rating_avg"], r["rating_count"]) == (4.5, 2)
    client.portal.call(bus.deliver, "review.created", {"restaurant_id": "ghost", "rating_avg": 1, "rating_count": 1})
