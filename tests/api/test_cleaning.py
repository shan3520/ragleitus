from fastapi.testclient import TestClient
from app.main import app
from app.core.middleware import rate_limiter
from tests.helpers import login, unique_username

def test_clean_endpoint():
    rate_limiter.reset()
    client = TestClient(app)
    headers, _ = login(client, unique_username("cleaner"))

    payload = {"pages": ["\x00Header text\nPage 1 content\nWhitespace   test"]}
    response = client.post("/clean", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "pages" in data
    assert len(data["pages"]) == 1
    assert "\x00" not in data["pages"][0]


def test_clean_requires_authentication():
    response = TestClient(app).post("/clean", json={"pages": ["x"]})
    assert response.status_code == 401
