from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_app_initialization():
    # Test that OpenAPI docs are available
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "openapi" in response.json()
    
    # Check that settings were loaded (by checking title in OpenAPI spec)
    openapi_schema = response.json()
    assert openapi_schema["info"]["title"] == "FastAPI App"
