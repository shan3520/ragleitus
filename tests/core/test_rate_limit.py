"""Tests for app.core.rate_limit."""

import time

from app.core.rate_limit import RateLimiter


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
