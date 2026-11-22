import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import build_app
from common.auth import create_access_token
from common.messaging import InMemoryEventBus

SECRET = "test-secret-test-secret-test-secret"


def headers(user_id: str, role: str = "customer") -> dict:
    tok = create_access_token(user_id=user_id, email=f"{user_id}@t.io", role=role, secret=SECRET,
                              algorithm="HS256", ttl_minutes=5)
    return {"Authorization": f"Bearer {tok}"}


CUSTOMER, OTHER, OWNER = headers("cust"), headers("other"), headers("owner", "restaurant")


class FakeOrders:
    def __init__(self):
        self.delivered = []

    async def get(self, path, params=None, **_):
        return self.delivered

    async def close(self): ...


@pytest.fixture
def orders():
    return FakeOrders()


@pytest.fixture
def bus():
    return InMemoryEventBus("review-service")


@pytest.fixture
def client(tmp_path, bus, orders):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db", jwt_secret=SECRET, outbox_poll_seconds=0.05)
    with TestClient(build_app(settings, bus=bus, orders_client=orders)) as c:
        yield c


def delivered(client, bus, order_id="o1", customer="cust"):
    client.portal.call(bus.deliver, "order.delivered", {
        "order_id": order_id, "number": order_id.upper(), "customer_id": customer, "restaurant_id": "r1",
        "restaurant_owner_id": "owner", "restaurant_name": "Тесто", "customer_name": "Мария Ионеску"})


def wait_events(bus, n, timeout=2.0):
    deadline = time.time() + timeout
    while len(bus.published) < n and time.time() < deadline:
        time.sleep(0.02)
    return bus.types()
