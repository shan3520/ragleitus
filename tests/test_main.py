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
