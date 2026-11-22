"""Сквозные (end-to-end) тесты всей системы через API Gateway.

Система должна быть запущена:  docker compose up -d --build
Запуск тестов:
    pip install -r tests/requirements.txt
    pytest tests/e2e -v

Переменная E2E_BASE_URL — адрес gateway (по умолчанию http://localhost:8080).
Тесты создают своих пользователей и свой ресторан, поэтому не зависят от демо-данных и их можно запускать много раз.
"""

import os
import time
import uuid

import httpx
import pytest

BASE = os.getenv("E2E_BASE_URL", "http://localhost:8080")
GOOD_CARD = {"card_number": "4242 4242 4242 4242", "exp_month": 12, "exp_year": 30, "cvc": "123"}
BAD_CARD = GOOD_CARD | {"card_number": "4000 0000 0000 0002"}


def wait_for(fn, timeout=20.0, what="condition"):
    """События идут через RabbitMQ асинхронно — ждём, пока система придёт в нужное состояние."""
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(0.4)
    raise AssertionError(f"Не дождались: {what}; последнее значение: {last!r}")


@pytest.fixture(scope="module")
def http():
    try:
        httpx.get(f"{BASE}/health", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"Gateway {BASE} недоступен — сначала запустите docker compose up -d")
    with httpx.Client(base_url=BASE, timeout=30) as client:
        yield client


def account(http, role: str) -> dict:
    email = f"e2e-{role}-{uuid.uuid4().hex[:8]}@test.md"
    r = http.post("/api/auth/register", json={"email": email, "password": "e2e-password", "role": role,
                                              "full_name": f"E2E {role}", "phone": "+373 60 000 000"})
    assert r.status_code == 201, r.text
    r = http.post("/api/auth/login", json={"email": email, "password": "e2e-password"})
    assert r.status_code == 200, r.text
    return {"id": r.json()["user"]["id"], "h": {"Authorization": f"Bearer {r.json()['access_token']}"}}


@pytest.fixture(scope="module")
def customer(http):
    return account(http, "customer")


@pytest.fixture(scope="module")
def owner(http):
    return account(http, "restaurant")


@pytest.fixture(scope="module")
def courier(http):
    return account(http, "courier")


@pytest.fixture(scope="module")
def restaurant(http, owner):
    r = http.post("/api/restaurants", json={"name": f"E2E Кухня {uuid.uuid4().hex[:4]}", "cuisine": "Молдавская",
                                            "address": "ул. Тестовая, 1", "delivery_fee": 20, "min_order": 50},
                  headers=owner["h"])
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    items = {}
    for name, price in (("Плачинта", 45), ("Зама", 55), ("Компот", 25)):
        r = http.post(f"/api/restaurants/{rid}/menu", json={"name": name, "price": price, "category": "Основное"},
                      headers=owner["h"])
        assert r.status_code == 201, r.text
        items[name] = r.json()["id"]
    return {"id": rid, "items": items}


def place_order(http, customer, restaurant, items=(("Плачинта", 2), ("Компот", 1))):
    r = http.post("/api/orders", headers=customer["h"] | {"Idempotency-Key": uuid.uuid4().hex}, json={
        "restaurant_id": restaurant["id"], "delivery_address": "ул. Букурешть, 41, кв. 5",
        "items": [{"menu_item_id": restaurant["items"][n], "quantity": q} for n, q in items]})
    assert r.status_code == 201, r.text
    return r.json()


def order_status(http, customer, order_id):
    return http.get(f"/api/orders/{order_id}", headers=customer["h"]).json()["status"]


def pay(http, customer, order_id, card):
    # платёж создаётся асинхронно по событию order.created
    wait_for(lambda: http.get(f"/api/payments/order/{order_id}", headers=customer["h"]).status_code == 200,
             what="платёж создан")
    return http.post(f"/api/payments/order/{order_id}/pay", json=card, headers=customer["h"])


# ---------------------------------------------------------------- инфраструктура

def test_gateway_health_request_id_and_hidden_internal_api(http):
    assert http.get("/health").json()["status"] == "ok"
    r = http.get("/api/orders", headers={"X-Request-ID": "e2e-trace-42"})
    assert r.status_code == 401
    assert r.headers["X-Request-ID"] == "e2e-trace-42" and r.json()["error"]["request_id"] == "e2e-trace-42"
    assert http.get("/internal/orders?status=ready").status_code == 404  # внутренние API наружу не проброшены
    assert http.get("/api/unknown").json()["error"]["code"] == "not_found"


def test_validation_error_format(http):
    r = http.post("/api/auth/register", json={"email": "not-email", "password": "1", "full_name": ""})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error" and {d["field"] for d in err["details"]} >= {"email", "password"}
    assert "Traceback" not in r.text


# ---------------------------------------------------------------- главный сценарий

def test_full_order_saga(http, customer, owner, courier, restaurant):
    order = place_order(http, customer, restaurant)
    assert order["status"] == "pending_payment"
    assert (order["subtotal"], order["delivery_fee"], order["total"]) == (115.0, 20.0, 135.0)  # цены считает ресторан
    oid = order["id"]

    # оплата: отказ банка, затем успех → saga переводит заказ в «оплачен»
    declined = pay(http, customer, oid, BAD_CARD)
    assert declined.status_code == 402 and declined.json()["error"]["code"] == "card_declined"
    assert pay(http, customer, oid, GOOD_CARD).status_code == 200
    wait_for(lambda: order_status(http, customer, oid) == "paid", what="заказ оплачен")

    # ресторан видит заказ, принимает и отмечает готовность
    assert any(o["id"] == oid for o in http.get("/api/orders?active=true", headers=owner["h"]).json())
    assert http.post(f"/api/orders/{oid}/accept", headers=owner["h"]).json()["status"] == "cooking"
    assert http.post(f"/api/orders/{oid}/ready", headers=owner["h"]).json()["status"] == "ready"

    # курьер выходит на линию, берёт заказ, забирает и доставляет
    assert http.put("/api/deliveries/couriers/me", json={"is_online": True}, headers=courier["h"]).status_code == 200
    delivery = wait_for(lambda: next((d for d in http.get("/api/deliveries/available", headers=courier["h"]).json()
                                      if d["order_id"] == oid), None), what="заказ у курьеров")
    did = delivery["id"]
    assert http.post(f"/api/deliveries/{did}/claim", headers=courier["h"]).json()["status"] == "assigned"
    wait_for(lambda: order_status(http, customer, oid) == "courier_assigned", what="курьер назначен")
    http.post(f"/api/deliveries/{did}/pickup", headers=courier["h"])
    http.post(f"/api/deliveries/{did}/deliver", headers=courier["h"])
    final = wait_for(lambda: (o := http.get(f"/api/orders/{oid}", headers=customer["h"]).json())["status"] == "delivered" and o,
                     what="заказ доставлен")
    assert [h["status"] for h in final["history"]] == ["pending_payment", "paid", "cooking", "ready",
                                                      "courier_assigned", "in_delivery", "delivered"]
    assert final["courier_name"] == "E2E courier"
    http.put("/api/deliveries/couriers/me", json={"is_online": False}, headers=courier["h"])

    # отзыв → рейтинг ресторана в каталоге
    wait_for(lambda: http.get(f"/api/reviews/order/{oid}", headers=customer["h"]).json()["can_review"], what="можно оценить")
    r = http.post("/api/reviews", json={"order_id": oid, "rating": 5, "comment": "E2E: всё отлично"}, headers=customer["h"])
    assert r.status_code == 201, r.text
    wait_for(lambda: http.get(f"/api/restaurants/{restaurant['id']}").json()["rating_count"] == 1, what="рейтинг обновлён")

    # уведомления дошли всем участникам
    def kinds(user):
        return {n["kind"] for n in http.get("/api/notifications?limit=50", headers=user["h"]).json()}
    wait_for(lambda: {"order.created", "order.paid", "delivery.assigned", "order.delivered"} <= kinds(customer),
             what="уведомления клиента")
    wait_for(lambda: {"order.paid", "review.created"} <= kinds(owner), what="уведомления ресторана")
    wait_for(lambda: "delivery.delivered" in kinds(courier), what="уведомление курьера")


# ---------------------------------------------------------------- компенсации и ошибки

def test_three_declines_cancel_the_order(http, customer, restaurant):
    oid = place_order(http, customer, restaurant)["id"]
    for _ in range(2):
        assert pay(http, customer, oid, BAD_CARD).status_code == 402
    r = pay(http, customer, oid, BAD_CARD)
    assert r.status_code == 402 and r.json()["error"]["code"] == "payment_failed"
    wait_for(lambda: order_status(http, customer, oid) == "cancelled", what="заказ отменён после отказов банка")


def test_restaurant_rejects_paid_order_and_money_is_refunded(http, customer, owner, restaurant):
    oid = place_order(http, customer, restaurant)["id"]
    assert pay(http, customer, oid, GOOD_CARD).status_code == 200
    wait_for(lambda: order_status(http, customer, oid) == "paid", what="заказ оплачен")
    r = http.post(f"/api/orders/{oid}/cancel", json={"reason": "Закончилось тесто"}, headers=owner["h"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    wait_for(lambda: http.get(f"/api/payments/order/{oid}", headers=customer["h"]).json()["status"] == "refunded",
             what="возврат денег")


def test_business_rules_and_access_control(http, customer, owner, restaurant):
    stranger = account(http, "customer")
    oid = place_order(http, customer, restaurant)["id"]
    assert http.get(f"/api/orders/{oid}", headers=stranger["h"]).status_code == 404
    assert http.post("/api/orders", json={}, headers=owner["h"]).status_code in (403, 422)
    assert http.post(f"/api/restaurants/{restaurant['id']}/menu", json={"name": "Чужое", "price": 1},
                     headers=stranger["h"]).status_code == 403

    # ниже минимальной суммы заказа
    r = http.post("/api/orders", headers=customer["h"], json={
        "restaurant_id": restaurant["id"], "delivery_address": "ул. Тестовая, 2",
        "items": [{"menu_item_id": restaurant["items"]["Компот"], "quantity": 1}]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "below_min_order"

    # ресторан закрыт
    http.patch(f"/api/restaurants/{restaurant['id']}", json={"is_open": False}, headers=owner["h"])
    try:
        r = http.post("/api/orders", headers=customer["h"], json={
            "restaurant_id": restaurant["id"], "delivery_address": "ул. Тестовая, 2",
            "items": [{"menu_item_id": restaurant["items"]["Зама"], "quantity": 2}]})
        assert r.status_code == 409 and r.json()["error"]["code"] == "restaurant_closed"
    finally:
        http.patch(f"/api/restaurants/{restaurant['id']}", json={"is_open": True}, headers=owner["h"])


def test_idempotency_key_prevents_double_order(http, customer, restaurant):
    key = uuid.uuid4().hex
    body = {"restaurant_id": restaurant["id"], "delivery_address": "ул. Тестовая, 3",
            "items": [{"menu_item_id": restaurant["items"]["Зама"], "quantity": 1}]}
    first = http.post("/api/orders", json=body, headers=customer["h"] | {"Idempotency-Key": key})
    second = http.post("/api/orders", json=body, headers=customer["h"] | {"Idempotency-Key": key})
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
