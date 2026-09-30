from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_register_login_and_me():
    # Register
    r = client.post("/auth/register", json={"username": "alice", "password": "wonderland"})
    assert r.status_code == 201
    assert r.json()["username"] == "alice"

    # Login
    r = client.post("/auth/login", json={"username": "alice", "password": "wonderland"})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    token = data["access_token"]

    # Me (protected)
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_login_invalid_credentials():
    r = client.post("/auth/login", json={"username": "noone", "password": "x"})
    assert r.status_code == 401


def test_register_duplicate():
    r = client.post("/auth/register", json={"username": "bob", "password": "secret-password"})
    assert r.status_code == 201
    r = client.post("/auth/register", json={"username": "bob", "password": "secret-password"})
    assert r.status_code == 400


def test_register_rejects_short_password():
    r = client.post("/auth/register", json={"username": "shorty", "password": "short"})
    assert r.status_code == 422


def test_me_requires_a_valid_token():
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_users_survive_in_the_database_not_process_memory():
    from app.db.database import SessionLocal
    from app.models.user import User

    client.post("/auth/register", json={"username": "persisted", "password": "password123"})
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.username == "persisted").one()
        assert user.password_hash.startswith("$argon2")
    finally:
        session.close()


def test_change_password():
    client.post("/auth/register", json={"username": "changer", "password": "password123"})
    token = client.post("/auth/login", json={"username": "changer", "password": "password123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.patch("/auth/me/password", json={"current_password": "wrong-password", "new_password": "newpassword1"}, headers=headers)
    assert r.status_code == 400

    r = client.patch("/auth/me/password", json={"current_password": "password123", "new_password": "newpassword1"}, headers=headers)
    assert r.status_code == 204

    assert client.post("/auth/login", json={"username": "changer", "password": "password123"}).status_code == 401
    assert client.post("/auth/login", json={"username": "changer", "password": "newpassword1"}).status_code == 200
