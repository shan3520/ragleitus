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


def test_rotating_forwarded_for_does_not_escape_the_limit():
    rate_limiter.reset()
    client = TestClient(create_app())
    statuses = [
        client.get("/health", headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code for i in range(21)
    ]
    assert statuses[:20] == [200] * 20
    assert statuses[20] == 429
    rate_limiter.reset()


def test_signed_in_users_have_their_own_buckets():
    from tests.helpers import login, unique_username

    rate_limiter.reset()
    client = TestClient(create_app())
    alice, _ = login(client, unique_username("alice"))
    bob, _ = login(client, unique_username("bob"))
    rate_limiter.reset()

    for _ in range(20):
        assert client.get("/auth/me", headers=alice).status_code == 200
    assert client.get("/auth/me", headers=alice).status_code == 429
    # Same address, different user: not throttled by Alice's requests.
    assert client.get("/auth/me", headers=bob).status_code == 200
    rate_limiter.reset()
