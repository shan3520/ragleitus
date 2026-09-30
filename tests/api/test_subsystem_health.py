from fastapi.testclient import TestClient
from app.main import app
from app.core.middleware import rate_limiter

def test_subsystem_health():
    rate_limiter.reset()
    client = TestClient(app)
    resp = client.get("/api/health/subsystems")
    assert resp.status_code == 200
    assert resp.json()["db"] == "healthy"
    assert resp.json()["vector_store"] == "healthy"


def test_subsystem_health_reports_unavailable_vector_store(monkeypatch):
    from app.services.vector_store import get_vector_store

    monkeypatch.setattr(get_vector_store(), "ping", lambda: False)
    resp = TestClient(app).get("/api/health/subsystems")
    assert resp.status_code == 503
    assert resp.json() == {"db": "healthy", "vector_store": "unavailable"}
