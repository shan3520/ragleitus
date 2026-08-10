'''Simple TTL in-memory cache.'''
import time

class MemoryCache:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self.store = {}

    def set(self, key: str, val: any):
        self.store[key] = (val, time.time())

    def get(self, key: str):
        if key not in self.store:
            return None
        val, ts = self.store[key]
        if time.time() - ts > self.ttl:
            del self.store[key]
            return None
        return val
