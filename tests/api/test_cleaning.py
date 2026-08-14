from fastapi.testclient import TestClient
from app.main import app
from app.core.middleware import rate_limiter

def test_clean_endpoint():
    rate_limiter.reset()
    client = TestClient(app)

    payload = {"pages": ["\x00Header text\nPage 1 content\nWhitespace   test"]}
    response = client.post("/clean", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "pages" in data
    assert len(data["pages"]) == 1
    assert "\x00" not in data["pages"][0]
