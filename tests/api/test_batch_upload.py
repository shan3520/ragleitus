from fastapi.testclient import TestClient
from app.main import app
from app.core.middleware import rate_limiter

def test_batch_status():
    rate_limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"username": "b_user", "password": "pass"})
    token = client.post("/auth/login", json={"username": "b_user", "password": "pass"}).json()["access_token"]
    resp = client.post("/api/documents/batch-status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
