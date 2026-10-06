"""Token-bucket rate limiters.

`RateLimiter` keeps its buckets in this process's memory: right for one API
process. `RedisRateLimiter` keeps them in Redis, so every API process (and
every host) draws from the same allowance; `create` picks one by
RATE_LIMIT_BACKEND.

If Redis can't be reached, the Redis limiter falls back to an in-memory one
for a few seconds at a time: requests stay limited (per process, as without
Redis) rather than going unlimited, and an outage never locks everyone out.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class RateLimiter:
    """Token-bucket rate limiter keyed by an arbitrary string (e.g. IP or user ID)."""

    # Calls never wait on I/O (see RedisRateLimiter).
    blocking = False

    def __init__(self, rate: float = 10.0, capacity: int = 20) -> None:
        """
        Parameters
        ----------
        rate : float
            Tokens added per second.
        capacity : int
            Maximum burst size (bucket depth).
        """
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.rate = rate
        self.capacity = capacity
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=float(capacity))
        )

    def _refill(self, bucket: _Bucket) -> None:
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.rate)
        bucket.last_refill = now

    def acquire(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """Consume *cost* tokens if the bucket has them.

        Returns (allowed, seconds until *cost* tokens are available again).
        """
        with self._lock:
            bucket = self._buckets[key]
            self._refill(bucket)
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True, 0.0
            return False, (cost - bucket.tokens) / self.rate

    def allow(self, key: str, cost: float = 1.0) -> bool:
        """Return ``True`` and consume *cost* tokens if the bucket has capacity."""
        return self.acquire(key, cost)[0]

    def remaining(self, key: str) -> int:
        """Return the number of remaining whole tokens for *key*."""
        with self._lock:
            bucket = self._buckets[key]
            self._refill(bucket)
            return int(bucket.tokens)

    def reset(self, key: Optional[str] = None) -> None:
        """Reset one or all buckets to full capacity."""
        with self._lock:
            if key is None:
                self._buckets.clear()
            elif key in self._buckets:
                del self._buckets[key]


# One atomic step of a bucket stored as a hash {tokens, ts}. Time comes from
# Redis, so API hosts with different clocks share one consistent bucket. The
# key expires once the bucket would be full again, so idle clients cost nothing.
# Returns {allowed (1/0), tokens left (as a string: Lua numbers become integers)}.
_TOKEN_BUCKET = """
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local stored = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(stored[1])
local ts = tonumber(stored[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate / 1000)
local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', KEYS[1], math.ceil((capacity - tokens) / rate * 1000) + 1000)
return {allowed, tostring(tokens)}
"""

KEY_PREFIX = "ragleitus:rl"


class RedisRateLimiter:
    """The same token bucket, stored in Redis and shared by every process using it."""

    # Each call is a network round trip: async callers run it in a thread.
    blocking = True

    # After Redis fails, use the in-memory fallback this long before trying again.
    RETRY_AFTER_FAILURE_SECONDS = 5.0
    # Warn about the fallback at most this often.
    WARN_INTERVAL_SECONDS = 60.0

    def __init__(self, name: str, rate: float, capacity: int, client) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.name = name
        self.rate = rate
        self.capacity = capacity
        self._client = client
        self._script = client.register_script(_TOKEN_BUCKET)
        self._fallback = RateLimiter(rate, capacity)
        self._down_until = 0.0
        self._warned_at = -math.inf
        self._lock = threading.Lock()

    def _key(self, key: str) -> str:
        return f"{KEY_PREFIX}:{self.name}:{key}"

    def _redis_available(self) -> bool:
        return time.monotonic() >= self._down_until

    def _failed(self, exc: Exception) -> None:
        now = time.monotonic()
        with self._lock:
            self._down_until = now + self.RETRY_AFTER_FAILURE_SECONDS
            warn = now - self._warned_at >= self.WARN_INTERVAL_SECONDS
            if warn:
                self._warned_at = now
        if warn:
            logger.warning(
                "Rate limiter cannot reach Redis; limiting per process meanwhile",
                extra={"limiter": self.name, "error": type(exc).__name__},
            )

    def _run(self, key: str, cost: float) -> tuple[bool, float] | None:
        """(allowed, tokens left) from Redis, or None when Redis is unavailable."""
        import redis

        if not self._redis_available():
            return None
        try:
            allowed, tokens = self._script(keys=[self._key(key)], args=[self.rate, self.capacity, cost])
        except redis.RedisError as exc:
            self._failed(exc)
            return None
        return bool(int(allowed)), float(tokens)

    def acquire(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """Consume *cost* tokens if the bucket has them: (allowed, seconds to wait if not)."""
        result = self._run(key, cost)
        if result is None:
            return self._fallback.acquire(key, cost)
        allowed, tokens = result
        return allowed, 0.0 if allowed else (cost - tokens) / self.rate

    def allow(self, key: str, cost: float = 1.0) -> bool:
        return self.acquire(key, cost)[0]

    def remaining(self, key: str) -> int:
        result = self._run(key, 0)
        return self._fallback.remaining(key) if result is None else int(result[1])

    def reset(self, key: Optional[str] = None) -> None:
        """Reset one or all of this limiter's buckets."""
        import redis

        self._fallback.reset(key)
        try:
            if key is not None:
                self._client.delete(self._key(key))
                return
            batch = []
            for stored in self._client.scan_iter(match=f"{KEY_PREFIX}:{self.name}:*", count=500):
                batch.append(stored)
                if len(batch) >= 500:
                    self._client.delete(*batch)
                    batch.clear()
            if batch:
                self._client.delete(*batch)
        except redis.RedisError as exc:
            self._failed(exc)


def redis_client(url: str):
    """A Redis client that gives up quickly, so a slow Redis can't stall requests."""
    import redis

    return redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5, health_check_interval=30)


def create(name: str, rate: float, capacity: int, backend: str | None = None, client=None):
    """The limiter for RATE_LIMIT_BACKEND (or `backend`): "memory" or "redis".

    `name` keeps limiters apart in Redis (e.g. "http", "login").
    """
    from app.core.config import settings

    backend = backend or settings.rate_limit_backend
    if backend == "memory":
        return RateLimiter(rate, capacity)
    if backend == "redis":
        return RedisRateLimiter(name, rate, capacity, client or redis_client(settings.redis_url))
    raise ValueError(f"unknown rate limit backend {backend!r}")


def retry_after_header(seconds: float) -> str:
    """Whole seconds for a Retry-After header, at least 1."""
    return str(max(1, math.ceil(seconds)))
