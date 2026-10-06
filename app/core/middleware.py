"""
Request-scoped middleware: assigns a unique request ID, measures latency,
and enforces token-bucket rate limits (see app.core.rate_limit).
"""

import logging
import time
import uuid

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core import metrics, rate_limit
from app.core.client_identity import rate_limit_key
from app.core.config import settings

logger = logging.getLogger(__name__)

# Requests per client (see RATE_LIMIT_BACKEND: per process, or shared in Redis).
rate_limiter = rate_limit.create(
    "http",
    rate=settings.rate_limit_per_minute / 60.0,
    capacity=settings.rate_limit_burst,
)

# Login attempts per account (see login_attempt).
login_rate_limiter = rate_limit.create(
    "login",
    rate=settings.login_attempts_per_minute / 60.0,
    capacity=settings.login_attempts_burst,
)


def login_attempt(username: str) -> tuple[bool, float]:
    """Count a login attempt for this username: (allowed, seconds to wait if not).

    Keyed by account, not address, so guessing one user's password is bounded
    however many addresses (or forged X-Forwarded-For values) the guesses come from.
    """
    return login_rate_limiter.acquire(f"login:{username.strip().lower()}")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique ID to every request and log basic timing info."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.monotonic()

        # Store on request state so downstream handlers can access it
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled error",
                extra={"request_id": request_id, "path": request.url.path},
            )
            _observe(request, 500, time.monotonic() - start)
            raise

        _observe(request, response.status_code, time.monotonic() - start)
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)

        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
        return response


def _observe(request: Request, status: int, seconds: float) -> None:
    # The route's path template, never the raw path: /api/documents/{document_id}.
    route = request.scope.get("route")
    template = getattr(route, "path", None) or "unmatched"
    metrics.HTTP_REQUESTS.labels(request.method, template, str(status)).inc()
    metrics.HTTP_DURATION.labels(request.method, template).observe(seconds)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket HTTP rate limiting middleware."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Exclude OpenAPI and docs endpoints from rate limiting
        path = request.url.path
        if path in ("/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # The signed-in user, or the client address (X-Forwarded-For only from trusted proxies).
        key = rate_limit_key(request)

        if rate_limiter.blocking:  # a Redis round trip: keep it off the event loop
            allowed, wait = await run_in_threadpool(rate_limiter.acquire, key)
        else:
            allowed, wait = rate_limiter.acquire(key)
        if not allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={"client": key, "path": path},
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": rate_limit.retry_after_header(wait)},
            )

        return await call_next(request)
