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


def test_bm25_index_weights_rare_terms_above_common_ones():
    from app.services.bm25 import BM25Index

    docs = [
        "the policy covers the refund window",
        "the office is open on the weekend",
        "the the the the the",
    ]
    index = BM25Index(docs)
    # "the" is in every document, "refund" in one: the refund document must win.
    assert index.top("the refund", limit=3)[0][0] == 0


def test_bm25_index_top_skips_non_matching_documents():
    from app.services.bm25 import BM25Index

    index = BM25Index(["alpha beta", "gamma delta"])
    assert [i for i, _ in index.top("delta", limit=5)] == [1]
    assert index.top("zeta", limit=5) == []
    assert BM25Index([]).top("anything", limit=5) == []
