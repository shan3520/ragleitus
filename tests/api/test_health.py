from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import settings

def test_health_endpoint():
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": True}

def test_version_endpoint():
    app = create_app()
    client = TestClient(app)
    response = client.get("/version")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data and "version" in data
    assert data["name"] == settings.PROJECT_NAME
    assert data["version"] == settings.VERSION
