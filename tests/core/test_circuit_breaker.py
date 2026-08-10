from app.core.circuit_breaker import CircuitBreaker
def test_circuit_breaker():
    cb = CircuitBreaker(failure_threshold=2)
    cb.record_failure()
    assert cb.is_open is False
    cb.record_failure()
    assert cb.is_open is True
