from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.core.security import InvalidTokenError, TokenClaims, bearer_token, decode_access_token


def _token(payload: dict, secret: str | None = None) -> str:
    return jwt.encode(payload, secret or settings.jwt_secret.get_secret_value(), algorithm="HS256")


def _soon() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=5)


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Bearer abc.def", "abc.def"),
        ("bearer   abc.def  ", "abc.def"),
        ("Basic dXNlcjpwYXNz", None),
        ("Bearer ", None),
        ("abc.def", None),
        ("", None),
        (None, None),
    ],
)
def test_bearer_token(header, expected):
    assert bearer_token(header) == expected


def test_decode_returns_user_and_version():
    assert decode_access_token(_token({"sub": "7", "ver": 3, "exp": _soon()})) == TokenClaims(7, 3)
    # Tokens issued before versions existed count as version 0.
    assert decode_access_token(_token({"sub": "7", "exp": _soon()})) == TokenClaims(7, 0)


@pytest.mark.parametrize(
    "token",
    [
        "garbage",
        _token({"sub": "7", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}),
        _token({"sub": "7", "exp": _soon()}, secret="another-secret-0123456789abcdefghijkl"),
        _token({"exp": _soon()}),
        _token({"sub": "not-a-number", "exp": _soon()}),
    ],
)
def test_decode_rejects_bad_tokens(token):
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)
