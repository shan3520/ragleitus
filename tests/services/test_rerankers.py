import pytest

from app.services import rerankers
from app.services.rerankers import FakeReranker, FastEmbedReranker


def test_the_fake_reranker_scores_by_shared_words():
    scores = FakeReranker().rerank("What does error E-4711 mean?", [
        "Employees receive 25 days of leave.",
        "Error E-4711 means the certificate expired.",
    ])
    assert scores[1] > scores[0]
    assert FakeReranker().rerank("", ["a"]) == [0.0]


class _StubCrossEncoder:
    loads = 0

    @staticmethod
    def list_supported_models():
        return [{"model": "Xenova/ms-marco-MiniLM-L-6-v2"}]

    def __init__(self, model_name, cache_dir=None):
        type(self).loads += 1
        self.model_name, self.cache_dir = model_name, cache_dir

    def rerank(self, query, documents):
        return (float(len(d)) for d in documents)


def test_the_local_reranker_loads_its_model_once_on_first_use(monkeypatch):
    import fastembed.rerank.cross_encoder as cross_encoder

    monkeypatch.setattr(cross_encoder, "TextCrossEncoder", _StubCrossEncoder)
    reranker = FastEmbedReranker("Xenova/ms-marco-MiniLM-L-6-v2", cache_dir="/models")
    assert _StubCrossEncoder.loads == 0  # nothing downloaded yet
    assert reranker.rerank("q", ["aa", "a"]) == [2.0, 1.0]
    assert reranker.rerank("q", ["abc"]) == [3.0]
    assert reranker.rerank("q", []) == []
    assert _StubCrossEncoder.loads == 1
    assert reranker._model.cache_dir == "/models"


def test_the_local_reranker_refuses_unknown_models(monkeypatch):
    import fastembed.rerank.cross_encoder as cross_encoder

    monkeypatch.setattr(cross_encoder, "TextCrossEncoder", _StubCrossEncoder)
    with pytest.raises(ValueError, match="does not support reranking model"):
        FastEmbedReranker("nope/model")


def test_tests_use_the_fake_local_reranker():
    rerankers.get_local_reranker.cache_clear()
    assert isinstance(rerankers.get_local_reranker(), FakeReranker)
