from fastapi.testclient import TestClient
from app.main import app
from app.core.middleware import rate_limiter

def test_config_summary():
    rate_limiter.reset()
    client = TestClient(app)
    resp = client.get("/api/config/summary")
    assert resp.status_code == 200
    assert "project" in resp.json()
