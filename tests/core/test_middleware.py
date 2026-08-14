from fastapi.testclient import TestClient
from app.main import create_app
from app.core.middleware import rate_limiter

def test_request_id_middleware_headers():
    rate_limiter.reset()
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert "X-Response-Time-Ms" in response.headers

def test_request_id_custom_header_preserved():
    rate_limiter.reset()
    app = create_app()
    client = TestClient(app)

    custom_id = "custom-req-id-123"
    response = client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id

def test_rate_limit_middleware_exceeded():
    rate_limiter.reset()
    app = create_app()
    client = TestClient(app)

    # Exhaust tokens for test client
    for _ in range(20):
        resp = client.get("/health")
        assert resp.status_code == 200

    # Next request should trigger 429
    overflow_resp = client.get("/health")
    assert overflow_resp.status_code == 429
    assert overflow_resp.json()["detail"] == "Too many requests. Please slow down."
    assert "Retry-After" in overflow_resp.headers
    rate_limiter.reset()
