from fastapi.testclient import TestClient
from app.main import app
from app.core.middleware import rate_limiter
from tests.helpers import login, unique_username

def test_config_summary():
    rate_limiter.reset()
    client = TestClient(app)
    headers, _ = login(client, unique_username("config"))
    resp = client.get("/api/config/summary", headers=headers)
    assert resp.status_code == 200
    assert "project" in resp.json()


def test_config_summary_requires_authentication():
    assert TestClient(app).get("/api/config/summary").status_code == 401
