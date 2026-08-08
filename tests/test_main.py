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
