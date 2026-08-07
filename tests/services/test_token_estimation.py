from app.services.token_estimation import estimate_token_count
def test_estimate_token_count():
    assert estimate_token_count("") == 0
    assert estimate_token_count("Hello world RAGForge") > 0
