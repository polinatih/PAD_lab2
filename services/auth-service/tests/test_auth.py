from conftest import login

ANN = {"email": "Ann@Mail.com", "password": "secret123", "full_name": "Анна", "phone": "+373 69 123456"}


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["checks"] == {"database": "ok", "rabbitmq": "ok"}


def test_register_login_me(client, bus):
    r = client.post("/api/auth/register", json=ANN)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "ann@mail.com" and body["role"] == "customer" and body["phone"] == "+373 69 123456"
    assert "password_hash" not in body
    assert bus.types() == ["user.registered"]
    assert bus.published[0]["data"]["role"] == "customer"

    r = client.post("/api/auth/login", json={"email": "ann@mail.com", "password": "secret123"})
    assert r.status_code == 200 and r.json()["user"]["full_name"] == "Анна"
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["id"] == body["id"]
    assert me.headers["X-Request-ID"]


def test_register_with_roles(client):
    for role in ("restaurant", "courier"):
        r = client.post("/api/auth/register", json=ANN | {"email": f"{role}@x.io", "role": role})
        assert r.status_code == 201 and r.json()["role"] == role
    # стать администратором через регистрацию нельзя
    r = client.post("/api/auth/register", json=ANN | {"email": "hacker@x.io", "role": "admin"})
    assert r.status_code == 422


def test_update_profile(client):
    client.post("/api/auth/register", json=ANN)
    h = login(client, "ann@mail.com", "secret123")
    r = client.patch("/api/auth/me", json={"full_name": "Анна К.", "phone": "+37360000000"}, headers=h)
    assert r.status_code == 200 and r.json()["full_name"] == "Анна К."
    assert client.patch("/api/auth/me", json={"phone": "not a phone"}, headers=h).status_code == 422


def test_duplicate_email(client):
    assert client.post("/api/auth/register", json=ANN).status_code == 201
    r = client.post("/api/auth/register", json=ANN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_validation_error_format(client):
    r = client.post("/api/auth/register", json={"email": "not-an-email", "password": "123", "full_name": "A"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert {d["field"] for d in err["details"]} == {"email", "password", "full_name"}


def test_wrong_password(client):
    client.post("/api/auth/register", json=ANN)
    r = client.post("/api/auth/login", json={"email": "ann@mail.com", "password": "wrong-pass"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"


def test_admin_endpoints(client):
    client.post("/api/auth/register", json=ANN | {"email": "u@u.io", "role": "courier"})
    user_h = login(client, "u@u.io", "secret123")
    admin_h = login(client, "admin@test.io", "adminpass1")

    assert client.get("/api/auth/users", headers=user_h).status_code == 403
    users = client.get("/api/auth/users", headers=admin_h).json()
    assert {u["email"] for u in users} == {"admin@test.io", "u@u.io"}
    assert [u["email"] for u in client.get("/api/auth/users", params={"role": "courier"}, headers=admin_h).json()] == ["u@u.io"]

    uid = next(u["id"] for u in users if u["email"] == "u@u.io")
    r = client.patch(f"/api/auth/users/{uid}/role", json={"role": "admin"}, headers=admin_h)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert client.patch("/api/auth/users/nope/role", json={"role": "customer"}, headers=admin_h).status_code == 404


def test_internal_user_lookup(client):
    uid = client.post("/api/auth/register", json=ANN).json()["id"]
    assert client.get(f"/internal/users/{uid}").status_code == 403
    r = client.get(f"/internal/users/{uid}", headers={"X-Internal-Key": "ik"})
    assert r.status_code == 200 and r.json()["phone"] == "+373 69 123456"
