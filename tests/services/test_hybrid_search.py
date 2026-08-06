from app.services.hybrid_search import combine_scores

def test_combine_scores():
    kw = {"doc1": 1.0, "doc2": 0.5}
    vec = {"doc1": 0.8, "doc3": 0.9}
    res = combine_scores(kw, vec, alpha=0.5)
    assert res["doc1"] == 0.9
    assert "doc3" in res
