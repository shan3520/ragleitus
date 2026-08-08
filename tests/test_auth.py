import sys
from pathlib import Path
# Ensure repo root is on sys.path for test collection environment
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
    r = client.post("/auth/register", json={"username": "bob", "password": "secret"})
    assert r.status_code == 201
    r = client.post("/auth/register", json={"username": "bob", "password": "secret"})
    assert r.status_code == 400
