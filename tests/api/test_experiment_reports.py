from fastapi.testclient import TestClient
from app.main import app
from app.core.middleware import rate_limiter

def test_experiment_report():
    rate_limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"username": "e_user", "password": "password123"})
    token = client.post("/auth/login", json={"username": "e_user", "password": "password123"}).json()["access_token"]
    resp = client.get("/api/experiments/report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
