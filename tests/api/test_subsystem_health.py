from fastapi.testclient import TestClient
from app.main import app
from app.core.middleware import rate_limiter

def test_subsystem_health():
    rate_limiter.reset()
    client = TestClient(app)
    resp = client.get("/api/health/subsystems")
    assert resp.status_code == 200
    assert resp.json()["db"] == "healthy"
