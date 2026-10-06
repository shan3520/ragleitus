import pytest
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
    for _ in range(rate_limiter.capacity):
        resp = client.get("/health")
        assert resp.status_code == 200

    # Next request should trigger 429
    overflow_resp = client.get("/health")
    assert overflow_resp.status_code == 429
    assert overflow_resp.json()["detail"] == "Too many requests. Please slow down."
    assert "Retry-After" in overflow_resp.headers
    rate_limiter.reset()


def _whoami_app(monkeypatch, trusted: list[str]):
    """The real app, with TRUSTED_PROXIES set, plus a route that reports what the app sees."""
    from fastapi import Request

    from app.core import config

    monkeypatch.setattr(config.settings, "trusted_proxies", trusted)
    app = create_app()

    @app.get("/_whoami")
    def whoami(request: Request):
        return {"client": request.client.host, "scheme": request.url.scheme}

    return app


def test_rotating_forwarded_for_does_not_escape_the_limit(monkeypatch):
    rate_limiter.reset()
    client = TestClient(_whoami_app(monkeypatch, []), client=("203.0.113.9", 5000))
    burst = rate_limiter.capacity
    statuses = [
        client.get("/health", headers={"X-Forwarded-For": f"198.51.100.{i % 250}"}).status_code
        for i in range(burst + 1)
    ]
    assert statuses[:burst] == [200] * burst
    assert statuses[burst] == 429
    rate_limiter.reset()


def test_proxy_headers_are_ignored_from_untrusted_peers(monkeypatch):
    rate_limiter.reset()
    client = TestClient(_whoami_app(monkeypatch, ["10.0.0.0/24"]), client=("203.0.113.9", 5000))
    body = client.get("/_whoami", headers={"X-Forwarded-For": "1.2.3.4", "X-Forwarded-Proto": "https"}).json()
    assert body == {"client": "203.0.113.9", "scheme": "http"}


@pytest.mark.parametrize(
    "forwarded_for, client_host",
    [
        ("198.51.100.7", "198.51.100.7"),
        ("1.2.3.4, 198.51.100.7", "198.51.100.7"),  # the left entry was written by the client
        ("198.51.100.7:41234", "198.51.100.7"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("198.51.100.7, 10.0.0.9", "198.51.100.7"),  # chain of trusted proxies
    ],
)
def test_trusted_proxy_reports_the_client_and_scheme(monkeypatch, forwarded_for, client_host):
    rate_limiter.reset()
    client = TestClient(_whoami_app(monkeypatch, ["10.0.0.0/24"]), client=("10.0.0.2", 5000))
    body = client.get("/_whoami", headers={"X-Forwarded-For": forwarded_for, "X-Forwarded-Proto": "https"}).json()
    assert body == {"client": client_host, "scheme": "https"}


def test_signed_in_users_have_their_own_buckets():
    from tests.helpers import login, unique_username

    rate_limiter.reset()
    client = TestClient(create_app())
    alice, _ = login(client, unique_username("alice"))
    bob, _ = login(client, unique_username("bob"))
    rate_limiter.reset()

    for _ in range(rate_limiter.capacity):
        assert client.get("/auth/me", headers=alice).status_code == 200
    assert client.get("/auth/me", headers=alice).status_code == 429
    # Same address, different user: not throttled by Alice's requests.
    assert client.get("/auth/me", headers=bob).status_code == 200
    rate_limiter.reset()


def test_a_revoked_token_cannot_use_up_the_new_sessions_allowance():
    from tests.helpers import TEST_PASSWORD, login, unique_username

    rate_limiter.reset()
    client = TestClient(create_app())
    old, _ = login(client, unique_username("victim"))
    new_token = client.patch(
        "/auth/me/password", json={"current_password": TEST_PASSWORD, "new_password": "a-new-password-1"}, headers=old
    ).json()["access_token"]
    new = {"Authorization": f"Bearer {new_token}"}
    rate_limiter.reset()

    for _ in range(rate_limiter.capacity + 1):
        client.get("/health", headers=old)  # e.g. whoever stole the old token
    assert client.get("/auth/me", headers=new).status_code == 200
    rate_limiter.reset()


def test_rate_limit_shared_through_redis_across_app_instances(monkeypatch):
    """Two API processes (two apps, two limiters) share one Redis-held allowance."""
    import fakeredis

    from app.core import middleware, rate_limit

    server = fakeredis.FakeServer()

    def limiter():
        return rate_limit.create("http", rate=1 / 60, capacity=3, backend="redis",
                                 client=fakeredis.FakeRedis(server=server))

    first, second = TestClient(create_app()), TestClient(create_app())
    statuses = []
    for client in (first, second, first, second):
        monkeypatch.setattr(middleware, "rate_limiter", limiter())
        statuses.append(client.get("/health").status_code)
    assert statuses == [200, 200, 200, 429]
    assert int(second.get("/health").headers["Retry-After"]) > 1
