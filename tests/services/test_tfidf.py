from app.services.tfidf import compute_tf, compute_idf

def test_compute_tf():
    tf = compute_tf(["a", "b", "a"])
    assert tf["a"] == 2/3
    assert tf["b"] == 1/3

def test_compute_idf():
    docs = [["a", "b"], ["a", "c"]]
    idf = compute_idf(docs)
    assert idf["a"] < idf["b"]
