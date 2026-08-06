from app.services.tfidf import compute_tf, compute_idf, normalize_vector

def test_compute_tf():
    tf = compute_tf(["a", "b", "a"])
    assert tf["a"] == 2/3
    assert tf["b"] == 1/3

def test_compute_idf():
    docs = [["a", "b"], ["a", "c"]]
    idf = compute_idf(docs)
    assert idf["a"] < idf["b"]

def test_normalize_vector():
    norm = normalize_vector({"a": 3.0, "b": 4.0})
    assert norm["a"] == 0.6
    assert norm["b"] == 0.8
