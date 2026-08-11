"""
In-memory sliding-window rate limiter.

Uses a per-client token bucket stored in a dict.  Designed for
single-process deployments; swap the backing store for Redis when
running behind multiple workers.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class RateLimiter:
    """Token-bucket rate limiter keyed by an arbitrary string (e.g. IP or user ID)."""

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
        self._buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=float(capacity))
        )

    def _refill(self, bucket: _Bucket) -> None:
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.rate)
        bucket.last_refill = now

    def allow(self, key: str, cost: float = 1.0) -> bool:
        """Return ``True`` and consume *cost* tokens if the bucket has capacity."""
        bucket = self._buckets[key]
        self._refill(bucket)
        if bucket.tokens >= cost:
            bucket.tokens -= cost
            return True
        return False

    def remaining(self, key: str) -> int:
        """Return the number of remaining whole tokens for *key*."""
        bucket = self._buckets[key]
        self._refill(bucket)
        return int(bucket.tokens)

    def reset(self, key: Optional[str] = None) -> None:
        """Reset one or all buckets to full capacity."""
        if key is None:
            self._buckets.clear()
        elif key in self._buckets:
            del self._buckets[key]
