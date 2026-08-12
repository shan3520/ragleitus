from app.services.jaccard_scoring import score_jaccard
def test_score_jaccard():
    assert score_jaccard("a b c", "b c d") == 0.5
