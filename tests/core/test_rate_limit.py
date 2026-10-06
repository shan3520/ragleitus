"""Tests for app.core.rate_limit."""

import time

import fakeredis
import pytest
import redis

from app.core import rate_limit
from app.core.rate_limit import RateLimiter, RedisRateLimiter


def test_allow_within_capacity():
    limiter = RateLimiter(rate=10, capacity=5)
    for _ in range(5):
        assert limiter.allow("user1") is True


def test_deny_when_exhausted():
    limiter = RateLimiter(rate=10, capacity=2)
    assert limiter.allow("user1") is True
    assert limiter.allow("user1") is True
    assert limiter.allow("user1") is False


def test_separate_keys_independent():
    limiter = RateLimiter(rate=10, capacity=1)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is False


def test_remaining_decreases():
    limiter = RateLimiter(rate=10, capacity=5)
    assert limiter.remaining("x") == 5
    limiter.allow("x")
    assert limiter.remaining("x") <= 5


def test_reset_all():
    limiter = RateLimiter(rate=10, capacity=3)
    limiter.allow("a")
    limiter.allow("b")
    limiter.reset()
    assert limiter.remaining("a") == 3
    assert limiter.remaining("b") == 3


def test_reset_single_key():
    limiter = RateLimiter(rate=10, capacity=3)
    limiter.allow("a")
    limiter.allow("b")
    limiter.reset("a")
    assert limiter.remaining("a") == 3


def test_invalid_rate_raises():
    try:
        RateLimiter(rate=0, capacity=5)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_invalid_capacity_raises():
    try:
        RateLimiter(rate=10, capacity=0)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_custom_cost():
    limiter = RateLimiter(rate=10, capacity=5)
    assert limiter.allow("user", cost=3) is True
    assert limiter.allow("user", cost=3) is False
    assert limiter.allow("user", cost=2) is True


# --- shared limits in Redis (fakeredis runs the Lua script in process) ------


@pytest.fixture
def server():
    return fakeredis.FakeServer()


def _redis(server):
    return fakeredis.FakeRedis(server=server)


def test_redis_limiter_allows_up_to_capacity_then_denies(server):
    limiter = RedisRateLimiter("http", rate=1, capacity=3, client=_redis(server))
    assert [limiter.allow("ip:1") for _ in range(4)] == [True, True, True, False]
    assert limiter.remaining("ip:1") == 0


def test_two_processes_share_one_allowance(server):
    # Two API processes, each with its own client, against the same Redis.
    first = RedisRateLimiter("http", rate=1, capacity=4, client=_redis(server))
    second = RedisRateLimiter("http", rate=1, capacity=4, client=_redis(server))
    results = [limiter.allow("user:7:v0") for limiter in (first, second, first, second, first)]
    assert results == [True, True, True, True, False]
    assert second.allow("user:7:v0") is False
    assert first.allow("user:8:v0") is True  # other clients are unaffected


def test_limiters_with_different_names_do_not_share(server):
    http = RedisRateLimiter("http", rate=1, capacity=1, client=_redis(server))
    login = RedisRateLimiter("login", rate=1, capacity=1, client=_redis(server))
    assert http.allow("k") and login.allow("k")
    assert not http.allow("k")


def test_redis_bucket_refills_over_time(server):
    client = _redis(server)
    limiter = RedisRateLimiter("http", rate=10, capacity=2, client=client)
    assert limiter.allow("k") and limiter.allow("k")
    allowed, wait = limiter.acquire("k")
    assert not allowed and 0 < wait <= 0.1
    time.sleep(0.15)
    assert limiter.allow("k")


def test_redis_bucket_expires_when_idle(server):
    client = _redis(server)
    limiter = RedisRateLimiter("http", rate=1, capacity=2, client=client)
    limiter.allow("k")
    ttl_ms = client.pttl(f"{rate_limit.KEY_PREFIX}:http:k")
    # One token short of full refills in 1 s; the key lives about that long, not forever.
    assert 0 < ttl_ms <= 2000


def test_redis_reset_one_and_all(server):
    limiter = RedisRateLimiter("http", rate=1, capacity=1, client=_redis(server))
    other = RedisRateLimiter("login", rate=1, capacity=1, client=_redis(server))
    limiter.allow("a"), limiter.allow("b"), other.allow("a")
    limiter.reset("a")
    assert limiter.allow("a") and not limiter.allow("b")
    limiter.reset()
    assert limiter.allow("b")
    assert not other.allow("a")  # reset only touches this limiter's buckets


class _DownRedis(fakeredis.FakeRedis):
    def evalsha(self, *args, **kwargs):
        raise redis.ConnectionError("connection refused")

    def eval(self, *args, **kwargs):
        raise redis.ConnectionError("connection refused")


def test_unreachable_redis_falls_back_to_a_per_process_limit(server, caplog):
    limiter = RedisRateLimiter("http", rate=1, capacity=2, client=_DownRedis(server=server))
    with caplog.at_level("WARNING", logger="app.core.rate_limit"):
        results = [limiter.allow("ip:9") for _ in range(3)]
    # Still limited, not open, and not locked out either.
    assert results == [True, True, False]
    warnings = [r for r in caplog.records if "cannot reach Redis" in r.getMessage()]
    assert len(warnings) == 1  # once, not per request
    assert "ip:9" not in caplog.text


def test_redis_is_tried_again_after_a_failure(server, monkeypatch):
    client = _redis(server)
    limiter = RedisRateLimiter("http", rate=1, capacity=1, client=client)
    limiter._failed(redis.ConnectionError())
    assert limiter.allow("k")  # served by the fallback meanwhile
    assert client.exists(f"{rate_limit.KEY_PREFIX}:http:k") == 0
    monkeypatch.setattr(limiter, "_down_until", 0.0)
    assert limiter.allow("k")  # back on Redis, whose bucket is still full
    assert client.exists(f"{rate_limit.KEY_PREFIX}:http:k") == 1


def test_create_picks_the_backend(server):
    assert isinstance(rate_limit.create("http", 1, 1, backend="memory"), RateLimiter)
    shared = rate_limit.create("http", 1, 1, backend="redis", client=_redis(server))
    assert isinstance(shared, RedisRateLimiter) and shared.blocking
    with pytest.raises(ValueError):
        rate_limit.create("http", 1, 1, backend="disk")


def test_memory_acquire_reports_the_wait():
    limiter = RateLimiter(rate=2, capacity=1)
    assert limiter.acquire("k") == (True, 0.0)
    allowed, wait = limiter.acquire("k")
    assert not allowed and 0.4 < wait <= 0.5


def test_retry_after_header_is_whole_seconds_at_least_one():
    assert rate_limit.retry_after_header(0.01) == "1"
    assert rate_limit.retry_after_header(1.2) == "2"
    assert rate_limit.retry_after_header(59.0) == "59"
