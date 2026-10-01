from datetime import datetime, timedelta, timezone

import jwt
import pytest
from starlette.requests import Request

from app.core.client_identity import rate_limit_key
from app.core.config import settings


def _request(path: str = "/api/documents", headers: dict[str, str] | None = None, peer: str = "203.0.113.9") -> Request:
    return Request({
        "type": "http", "method": "GET", "path": path, "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (peer, 1234),
    })


def _token(sub: str = "42", ver: int | None = 0, expires_in: timedelta = timedelta(minutes=5), secret: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "iat": now, "exp": now + expires_in}
    if ver is not None:
        payload["ver"] = ver
    return jwt.encode(payload, secret or settings.jwt_secret.get_secret_value(), algorithm="HS256")


def test_signed_in_requests_are_keyed_by_user_and_token_version():
    assert rate_limit_key(_request(headers={"Authorization": f"Bearer {_token()}"})) == "user:42:v0"
    # A token revoked by a password change has its own bucket, apart from the new session's.
    assert rate_limit_key(_request(headers={"Authorization": f"Bearer {_token(ver=1)}"})) == "user:42:v1"


def test_the_key_ignores_the_address_for_signed_in_requests():
    a = rate_limit_key(_request(headers={"Authorization": f"Bearer {_token()}"}, peer="10.9.9.9"))
    b = rate_limit_key(_request(headers={"Authorization": f"Bearer {_token()}", "X-Forwarded-For": "1.1.1.1"}))
    assert a == b == "user:42:v0"


@pytest.mark.parametrize("path", ["/auth/login", "/auth/register"])
def test_login_and_registration_are_always_keyed_by_address(path):
    # Otherwise tokens from many throwaway accounts would each bring their own allowance.
    request = _request(path, headers={"Authorization": f"Bearer {_token()}"})
    assert rate_limit_key(request) == "ip:203.0.113.9"


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer not-a-jwt",
        f"Bearer {_token(expires_in=timedelta(minutes=-5))}",
        f"Bearer {_token(secret='another-secret-0123456789abcdefghijkl')}",
        "Basic dXNlcjpwYXNz",
    ],
)
def test_invalid_tokens_fall_back_to_the_address(authorization):
    assert rate_limit_key(_request(headers={"Authorization": authorization})) == "ip:203.0.113.9"


def test_the_address_comes_from_the_connection_not_the_header():
    # Rewriting the address from X-Forwarded-For is ProxyHeadersMiddleware's job, for trusted proxies only.
    assert rate_limit_key(_request(headers={"X-Forwarded-For": "1.1.1.1"})) == "ip:203.0.113.9"
