import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import build_app
from common.messaging import InMemoryEventBus


@pytest.fixture
def bus():
    return InMemoryEventBus("auth-service")


@pytest.fixture
def client(tmp_path, bus):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db", password_iterations=1000,
                        admin_email="admin@test.io", admin_password="adminpass1", internal_api_key="ik")
    with TestClient(build_app(settings, bus=bus)) as c:
        yield c


def login(client, email, password) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
