from datetime import datetime, timedelta, timezone

import jwt
import pytest
from starlette.requests import Request

from app.core import client_identity
from app.core.client_identity import client_address, rate_limit_key
from app.core.config import settings

TRUSTED = ["10.0.0.0/24", "192.168.5.7"]


def test_header_from_an_untrusted_peer_is_ignored():
    assert client_address("203.0.113.9", "1.2.3.4", TRUSTED) == "203.0.113.9"
    assert client_address("203.0.113.9", "1.2.3.4", []) == "203.0.113.9"


def test_trusted_proxy_reports_the_client():
    assert client_address("10.0.0.2", "198.51.100.7", TRUSTED) == "198.51.100.7"


def test_entries_left_of_the_real_client_are_ignored():
    # The client sent "1.2.3.4" itself; the trusted proxy appended the real address.
    assert client_address("10.0.0.2", "1.2.3.4, 198.51.100.7", TRUSTED) == "198.51.100.7"


def test_chain_of_trusted_proxies_resolves_to_the_client():
    assert client_address("10.0.0.2", "198.51.100.7, 192.168.5.7, 10.0.0.9", TRUSTED) == "198.51.100.7"


def test_garbage_stops_at_the_last_vouched_address():
    assert client_address("10.0.0.2", "not-an-ip, 10.0.0.9", TRUSTED) == "10.0.0.9"
    assert client_address("10.0.0.2", "", TRUSTED) == "10.0.0.2"
    assert client_address("10.0.0.2", None, TRUSTED) == "10.0.0.2"


def test_ipv4_mapped_peer_matches_ipv4_networks():
    assert client_address("::ffff:10.0.0.2", "198.51.100.7", TRUSTED) == "198.51.100.7"


def _request(headers: dict[str, str], peer: str = "203.0.113.9") -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234),
    })


def _token(sub: str, expires_in: timedelta = timedelta(minutes=5), secret: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": sub, "iat": now, "exp": now + expires_in},
        secret or settings.jwt_secret.get_secret_value(), algorithm="HS256",
    )


def test_signed_in_requests_are_keyed_by_user_wherever_they_come_from():
    token = _token("42")
    assert rate_limit_key(_request({"Authorization": f"Bearer {token}"}, peer="10.9.9.9")) == "user:42"
    assert rate_limit_key(_request({"Authorization": f"bearer {token}", "X-Forwarded-For": "1.1.1.1"})) == "user:42"


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer not-a-jwt",
        f"Bearer {_token('42', expires_in=timedelta(minutes=-5))}",
        f"Bearer {_token('42', secret='another-secret-0123456789abcdefghijkl')}",
        "Basic dXNlcjpwYXNz",
    ],
)
def test_invalid_tokens_fall_back_to_the_address(authorization):
    request = _request({"Authorization": authorization, "X-Forwarded-For": "1.1.1.1"})
    assert rate_limit_key(request) == "ip:203.0.113.9"


def test_forwarded_address_is_used_only_from_configured_proxies(monkeypatch):
    request = _request({"X-Forwarded-For": "198.51.100.7"}, peer="10.0.0.2")
    assert rate_limit_key(request) == "ip:10.0.0.2"
    monkeypatch.setattr(client_identity.settings, "trusted_proxies", ["10.0.0.0/24"])
    assert rate_limit_key(request) == "ip:198.51.100.7"
