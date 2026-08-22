from app.services.hybrid_search import combine_scores

def test_combine_scores():
    kw = {"doc1": 1.0, "doc2": 0.5}
    vec = {"doc1": 0.8, "doc3": 0.9}
    res = combine_scores(kw, vec, alpha=0.5)
    # Default call still yields the paginated object shape.
    assert res["total"] == 3
    scores = dict(res["items"])
    assert scores["doc1"] == 0.9
    assert "doc3" in scores

def test_combine_scores_paginates_slice_and_total():
    kw = {f"doc{i}": float(i) for i in range(10)}
    vec = {}

    top = combine_scores(kw, vec, skip=0, limit=5)
    # A limit of 5 must never return more than 5 items.
    assert len(top["items"]) == 5
    # Highest combined scores come first.
    assert top["items"] == [
        ("doc9", 4.5),
        ("doc8", 4.0),
        ("doc7", 3.5),
        ("doc6", 3.0),
        ("doc5", 2.5),
    ]

    tail = combine_scores(kw, vec, skip=5, limit=5)
    # offset must shift the window rather than repeat or truncate it.
    assert {key for key, _ in tail["items"]} == {
        "doc4", "doc3", "doc2", "doc1", "doc0",
    }

    # total counts the full pre-sliced result set, not the page size.
    assert top["total"] == 10
    assert tail["total"] == 10

def test_combine_scores_offset_past_end_returns_empty_page_with_total():
    kw = {"doc1": 1.0, "doc2": 0.5}
    res = combine_scores(kw, {}, skip=50, limit=5)
    assert res["items"] == []
    assert res["total"] == 2
