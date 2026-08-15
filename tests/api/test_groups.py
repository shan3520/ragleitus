from fastapi.testclient import TestClient

from app.main import app

def test_create_group():
    client = TestClient(app)
    response = client.post("/api/groups", json={"name": "New Test Group"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Test Group"
    assert "id" in data
