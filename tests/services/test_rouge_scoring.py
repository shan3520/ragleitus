from app.services.rouge_scoring import score_rouge_l
def test_score_rouge_l():
    assert score_rouge_l("fastapi app", "fastapi framework app") > 0.0
    assert score_rouge_l("", "test") == 0.0
