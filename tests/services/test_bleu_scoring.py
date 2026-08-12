from app.services.bleu_scoring import score_bleu
def test_score_bleu():
    assert score_bleu("hello world", "hello world extra") == 1.0
