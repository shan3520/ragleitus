"""
Request-scoped middleware: assigns a unique request ID, measures latency,
and enforces sliding-window token-bucket rate limits.
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.client_identity import rate_limit_key
from app.core.config import settings
from app.core.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

# Global rate limiter instance for single-process middleware
rate_limiter = RateLimiter(
    rate=settings.rate_limit_per_minute / 60.0,
    capacity=settings.rate_limit_burst,
)


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
            raise

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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket HTTP rate limiting middleware."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Exclude OpenAPI and docs endpoints from rate limiting
        path = request.url.path
        if path in ("/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # The signed-in user, or the client address (X-Forwarded-For only from trusted proxies).
        key = rate_limit_key(request)

        if not rate_limiter.allow(key):
            logger.warning(
                "Rate limit exceeded",
                extra={"client": key, "path": path},
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
