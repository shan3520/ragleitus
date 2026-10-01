"""Access-token helpers shared by authentication and rate limiting.

Verifying a token's signature and expiry needs only the signing secret, so it
lives here (cross-cutting) rather than in a service. Whether the user still
exists and the token's version is current is checked by
app.services.auth_service.get_user_from_token.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt

from app.core.config import settings

ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    # Bumped on every password change; tokens with an older version are revoked.
    version: int


def bearer_token(authorization: str | None) -> str | None:
    """The token from an `Authorization: Bearer <token>` header, or None."""
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token else None


def decode_access_token(token: str) -> TokenClaims:
    """Verify signature and expiry (no database lookup). Raises InvalidTokenError."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        return TokenClaims(user_id=int(payload["sub"]), version=int(payload.get("ver", 0)))
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise InvalidTokenError(str(exc)) from exc
