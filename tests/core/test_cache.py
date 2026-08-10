from app.core.cache import MemoryCache
def test_memory_cache():
    c = MemoryCache(ttl_seconds=60)
    c.set("k1", "v1")
    assert c.get("k1") == "v1"
    assert c.get("k2") is None
