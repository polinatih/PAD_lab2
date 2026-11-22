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


CUSTOMER, OWNER, COURIER = headers("cust"), headers("owner", "restaurant"), headers("andrei", "courier")
ORDER = {"order_id": "o1", "number": "AB12CD", "customer_id": "cust", "restaurant_owner_id": "owner",
         "restaurant_name": "Тесто", "total": 318.0}


@pytest.fixture
def bus():
    return InMemoryEventBus("notification-service")


@pytest.fixture
def client(tmp_path, bus):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db", jwt_secret=SECRET)
    with TestClient(build_app(settings, bus=bus)) as c:
        yield c
