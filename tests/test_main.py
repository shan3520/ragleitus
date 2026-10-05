import threading
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)

def test_app_initialization():
    # Test that OpenAPI docs are available
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "openapi" in response.json()
    
    # Check that settings were loaded (by checking title and version in OpenAPI spec)
    openapi_schema = response.json()
    assert openapi_schema["info"]["title"] == settings.PROJECT_NAME
    assert openapi_schema["info"]["version"] == settings.VERSION

def test_version_endpoint():
    response = client.get("/version")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == settings.PROJECT_NAME
    assert data["version"] == settings.VERSION


PUBLIC_ROUTES = {
    ("GET", "/health"),
    ("GET", "/version"),
    ("GET", "/api/health/subsystems"),
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
}


def test_every_non_public_route_requires_authentication():
    """Guard against a new router forgetting the auth dependency."""
    import re

    from app.core.middleware import rate_limiter

    checked = 0
    for path, operations in app.openapi()["paths"].items():
        concrete_path = re.sub(r"\{[^}]+\}", "1", path)
        for method in operations:
            method = method.upper()
            if (method, path) in PUBLIC_ROUTES:
                continue
            rate_limiter.reset()
            response = client.request(method, concrete_path)
            assert response.status_code == 401, f"{method} {path} answered {response.status_code} without a token"
            checked += 1
    assert checked > 20


def test_startup_requeues_interrupted_indexing_and_starts_the_sweep(monkeypatch):
    from app import main
    from app.services import ingestion

    calls = []
    swept = threading.Event()

    def fake_requeue(*args, **kwargs):
        calls.append(kwargs)
        if not kwargs:
            swept.set()
        return []

    monkeypatch.setattr(ingestion, "requeue_stalled", fake_requeue)
    monkeypatch.setattr(main.settings, "task_queue", "inline")
    monkeypatch.setattr(main.settings, "index_sweep_minutes", 0.001)  # every ~60 ms
    with TestClient(main.create_app()):
        assert swept.wait(5)
    # Inline: everything unfinished was interrupted by the restart; then periodic sweeps.
    assert calls[0] == {"all_unfinished": True}
    assert {} in calls[1:]


def test_with_celery_the_api_only_sweeps_for_stale_documents(monkeypatch):
    from app import main
    from app.services import ingestion

    calls = []
    monkeypatch.setattr(ingestion, "requeue_stalled", lambda *a, **k: calls.append(k) or [])
    monkeypatch.setattr(main.settings, "task_queue", "celery")
    monkeypatch.setattr(main.settings, "index_sweep_minutes", 0)
    with TestClient(main.create_app()):
        pass
    assert calls == []
