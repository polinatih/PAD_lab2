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


def headers(user_id: str, role: str = "courier") -> dict:
    tok = create_access_token(user_id=user_id, email=f"{user_id}@t.io", role=role, secret=SECRET,
                              algorithm="HS256", ttl_minutes=5)
    return {"Authorization": f"Bearer {tok}"}


ANDREI, IGOR, CUSTOMER = headers("andrei"), headers("igor"), headers("cust", "customer")


@pytest.fixture
def bus():
    return InMemoryEventBus("delivery-service")


@pytest.fixture
def auth_state():
    return {"down": False}


class FakeOrders:
    """Подменяет order-service для сверки при старте."""

    def __init__(self):
        self.ready = []

    async def get(self, path, params=None, **_):
        return self.ready

    async def close(self): ...


@pytest.fixture
def orders():
    return FakeOrders()


@pytest.fixture
def client(tmp_path, bus, auth_state, orders):
    def auth_handler(request: httpx.Request):
        if auth_state["down"]:
            raise httpx.ConnectError("refused")
        uid = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"id": uid, "full_name": f"Курьер {uid}", "phone": "+37379000000"})

    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db", jwt_secret=SECRET, outbox_poll_seconds=0.05)
    auth = ServiceClient("auth-service", "http://a", internal_key="ik", retries=0, transport=httpx.MockTransport(auth_handler))
    with TestClient(build_app(settings, bus=bus, auth_client=auth, orders_client=orders)) as c:
        yield c


def order_ready(client, bus, order_id="o1"):
    client.portal.call(bus.deliver, "order.ready", {
        "order_id": order_id, "number": order_id.upper(), "customer_id": "cust", "customer_name": "Мария",
        "customer_phone": "+37369111222", "restaurant_name": "Тесто", "restaurant_address": "ул. Пушкина, 24",
        "delivery_address": "ул. Букурешть, 41", "comment": "Код 41", "total": 349.0, "delivery_fee": 25.0})


def online(client, h):
    assert client.put("/api/deliveries/couriers/me", json={"is_online": True}, headers=h).status_code == 200


def wait_events(bus, n, timeout=2.0):
    deadline = time.time() + timeout
    while len(bus.published) < n and time.time() < deadline:
        time.sleep(0.02)
    return bus.types()
