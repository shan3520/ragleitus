"""Who is making a request, for rate limiting.

The client address is `request.client.host`. X-Forwarded-For only changes it
when the connection comes from a proxy listed in TRUSTED_PROXIES: uvicorn's
ProxyHeadersMiddleware, installed by app.main with that list, rewrites the
address (and the scheme, from X-Forwarded-Proto) before this runs. The server
itself must run with --no-proxy-headers so uvicorn does not apply its own
default trust of 127.0.0.1 first.

Requests with a valid access token are keyed by their user instead, because a
token cannot be forged and it keeps users apart even when they reach the API
through the same proxy (the web app). The token's version is part of the key,
so a token revoked by a password change cannot use up the new session's
allowance. Login and registration always use the address: otherwise tokens
from many throwaway accounts would each bring their own allowance.
"""

from __future__ import annotations

from starlette.requests import Request

from app.core.security import InvalidTokenError, bearer_token, decode_access_token

# Signed-out endpoints: always limited per address, whatever token is sent.
ADDRESS_ONLY_PATHS = frozenset({"/auth/login", "/auth/register"})


def rate_limit_key(request: Request) -> str:
    """`user:<id>:v<version>` for a valid access token, else `ip:<client address>`."""
    if request.url.path not in ADDRESS_ONLY_PATHS:
        token = bearer_token(request.headers.get("Authorization"))
        if token is not None:
            try:
                claims = decode_access_token(token)
            except InvalidTokenError:
                pass
            else:
                return f"user:{claims.user_id}:v{claims.version}"
    return f"ip:{request.client.host if request.client else 'unknown'}"
