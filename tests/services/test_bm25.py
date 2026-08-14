from app.services.bm25 import tokenize, score_bm25

def test_tokenize():
    assert tokenize("Hello World! RAGForge 123.") == ["hello", "world", "ragforge", "123"]
    assert tokenize("") == []

def test_score_bm25():
    q = ["fastapi", "rag"]
    doc = ["fastapi", "is", "a", "framework", "for", "rag", "applications"]
    score = score_bm25(q, doc, avg_doc_len=7.0)
    assert score > 0.0

def test_score_bm25_empty():
    assert score_bm25([], ["foo"], 5.0) == 0.0
    assert score_bm25(["foo"], [], 5.0) == 0.0
