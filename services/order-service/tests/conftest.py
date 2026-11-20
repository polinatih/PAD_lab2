import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import build_app
from common.auth import create_access_token
from common.http import ServiceClient
from common.messaging import InMemoryEventBus

SECRET = "test-secret-test-secret-test-secret"


def headers(user_id: str, role: str = "customer") -> dict:
    tok = create_access_token(user_id=user_id, email=f"{user_id}@t.io", role=role, secret=SECRET,
                              algorithm="HS256", ttl_minutes=5)
    return {"Authorization": f"Bearer {tok}"}


CUSTOMER, OTHER = headers("cust"), headers("other")
OWNER, ADMIN = headers("owner", "restaurant"), headers("root", "admin")

MENU = {"m1": ("Маргарита", 129.0), "m2": ("Лимонад", 35.0)}


class Neighbors:
    """Поведение restaurant-service и auth-service, которое тест может менять."""

    def __init__(self):
        self.restaurant_mode = "ok"  # ok | down | closed
        self.auth_mode = "ok"        # ok | down
        self.quotes = 0

    def restaurant(self, request: httpx.Request):
        if self.restaurant_mode == "down":
            raise httpx.ConnectError("refused")
        if self.restaurant_mode == "closed":
            return httpx.Response(409, json={"error": {"code": "restaurant_closed", "message": "Ресторан закрыт"}})
        self.quotes += 1
        body = json.loads(request.content)
        lines = []
        for line in body["items"]:
            name, price = MENU[line["menu_item_id"]]
            lines.append({"menu_item_id": line["menu_item_id"], "name": name, "unit_price": price,
                          "quantity": line["quantity"], "line_total": price * line["quantity"]})
        subtotal = sum(l["line_total"] for l in lines)
        return httpx.Response(200, json={"restaurant_id": "r1", "restaurant_name": "Тесто", "restaurant_address": "Пушкина, 24",
                                         "owner_id": "owner", "prep_minutes": 20, "items": lines,
                                         "subtotal": subtotal, "delivery_fee": 25.0, "total": subtotal + 25})

    def auth(self, request: httpx.Request):
        if self.auth_mode == "down":
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"id": "cust", "full_name": "Мария", "phone": "+37369000000"})


@pytest.fixture
def neighbors():
    return Neighbors()


@pytest.fixture
def bus():
    return InMemoryEventBus("order-service")


@pytest.fixture
def client(tmp_path, bus, neighbors):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db", jwt_secret=SECRET, internal_api_key="ik",
                        outbox_poll_seconds=0.05)
    rest = ServiceClient("restaurant-service", "http://r", internal_key="ik", retries=0,
                         transport=httpx.MockTransport(neighbors.restaurant))
    auth = ServiceClient("auth-service", "http://a", internal_key="ik", retries=0,
                         transport=httpx.MockTransport(neighbors.auth))
    with TestClient(build_app(settings, bus=bus, restaurants_client=rest, auth_client=auth)) as c:
        yield c


def wait_events(bus, n, timeout=2.0):
    deadline = time.time() + timeout
    while len(bus.published) < n and time.time() < deadline:
        time.sleep(0.02)
    return bus.types()


ORDER = {"restaurant_id": "r1", "delivery_address": "ул. Букурешть, 41, кв. 5",
         "items": [{"menu_item_id": "m1", "quantity": 2}, {"menu_item_id": "m2", "quantity": 1}]}
