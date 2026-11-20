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


CUSTOMER, OTHER, ADMIN = headers("cust"), headers("other"), headers("root", "admin")
GOOD = {"card_number": "4242 4242 4242 4242", "exp_month": 12, "exp_year": 99, "cvc": "123"}
DECLINED = GOOD | {"card_number": "4000 0000 0000 0002"}


@pytest.fixture
def bus():
    return InMemoryEventBus("payment-service")


@pytest.fixture
def app(tmp_path, bus):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db", jwt_secret=SECRET,
                        outbox_poll_seconds=0.05, expiry_check_seconds=3600)
    return build_app(settings, bus=bus)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def order_created(client, bus, order_id="o1", total=318.0):
    client.portal.call(bus.deliver, "order.created", {"order_id": order_id, "number": "ABC123", "customer_id": "cust",
                                                      "restaurant_name": "Тесто", "total": total})


def wait_events(bus, n, timeout=2.0):
    deadline = time.time() + timeout
    while len(bus.published) < n and time.time() < deadline:
        time.sleep(0.02)
    return bus.types()
