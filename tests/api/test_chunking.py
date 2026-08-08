from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_chunk_text_short_text():
    response = client.post("/chunk", json={"text": "Short text."})
    assert response.status_code == 200
    assert response.json() == {"chunks": ["Short text."]}


def test_chunk_text_without_punctuation():
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    response = client.post("/chunk", json={"text": text, "chunk_window_size": 20, "chunk_overlap_size": 5})
    assert response.status_code == 200
    assert response.json()["chunks"] == ["alpha beta gamma del", "a delta epsilon zeta", "zeta eta theta iota", "iota kappa"]


def test_chunk_text_exact_boundary():
    text = "One sentence here. Two sentence here."
    response = client.post("/chunk", json={"text": text, "chunk_window_size": 18, "chunk_overlap_size": 0})
    assert response.status_code == 200
    assert response.json() == {"chunks": ["One sentence here.", "Two sentence here."]}
