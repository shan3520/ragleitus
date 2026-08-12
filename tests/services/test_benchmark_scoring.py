from app.services.benchmark_scoring import aggregate_benchmarks
def test_aggregate_benchmarks():
    res = aggregate_benchmarks([0.8, 0.9], [120.0, 140.0])
    assert res["avg_score"] == 0.85
    assert res["avg_latency_ms"] == 130.0
