'''Benchmark metrics aggregator.'''
def aggregate_benchmarks(scores: list[float], latencies_ms: list[float]) -> dict:
    if not scores:
        return {"avg_score": 0.0, "avg_latency_ms": 0.0}
    return {
        "avg_score": round(sum(scores) / len(scores), 4),
        "avg_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 2) if latencies_ms else 0.0,
    }
