import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import build_app
from common.auth import create_access_token
from common.messaging import InMemoryEventBus

SECRET = "test-secret-test-secret-test-secret"
INTERNAL = {"X-Internal-Key": "ik"}


def headers(user_id: str, role: str = "restaurant") -> dict:
    tok = create_access_token(user_id=user_id, email=f"{user_id}@t.io", role=role, secret=SECRET,
                              algorithm="HS256", ttl_minutes=5)
    return {"Authorization": f"Bearer {tok}"}


OWNER, OTHER_OWNER = headers("owner"), headers("other")
CUSTOMER, ADMIN = headers("cust", "customer"), headers("root", "admin")


@pytest.fixture
def bus():
    return InMemoryEventBus()


@pytest.fixture
def client(tmp_path, bus):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db", jwt_secret=SECRET, internal_api_key="ik")
    with TestClient(build_app(settings, bus=bus)) as c:
        yield c


@pytest.fixture
def restaurant(client):
    body = {"name": "Пиццерия «Тесто»", "cuisine": "Пицца", "address": "ул. Пушкина, 10", "delivery_fee": 25,
            "min_order": 100, "description": "Неаполитанская пицца из дровяной печи"}
    r = client.post("/api/restaurants", json=body, headers=OWNER)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    items = {}
    for name, price, cat in [("Маргарита", 129, "Пицца"), ("Пепперони", 149.5, "Пицца"), ("Лимонад", 35, "Напитки")]:
        r = client.post(f"/api/restaurants/{rid}/menu", json={"name": name, "price": price, "category": cat}, headers=OWNER)
        assert r.status_code == 201, r.text
        items[name] = r.json()["id"]
    return {"id": rid, "items": items}
