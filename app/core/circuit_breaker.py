'''Circuit Breaker state manager.'''
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3):
        self.threshold = failure_threshold
        self.failure_count = 0
        self.is_open = False

    def record_success(self):
        self.failure_count = 0
        self.is_open = False

    def record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.threshold:
            self.is_open = True
