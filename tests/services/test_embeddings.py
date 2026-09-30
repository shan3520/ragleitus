import math

import pytest

from app.services.embeddings import FakeEmbedder, FastEmbedEmbedder, get_embedder


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_fake_embedder_is_deterministic_and_normalised():
    embedder = FakeEmbedder()
    first = embedder.embed_query("Refund policy for annual plans")
    assert first == embedder.embed_query("Refund policy for annual plans")
    assert len(first) == embedder.dimension
    assert math.isclose(sum(v * v for v in first), 1.0, rel_tol=1e-9)


def test_fake_embedder_places_related_text_closer():
    embedder = FakeEmbedder()
    query = embedder.embed_query("refund policy")
    related, unrelated = embedder.embed_documents(["Our refund policy lasts 30 days.", "The office cat is named Miso."])
    assert _cosine(query, related) > _cosine(query, unrelated)


def test_tests_use_the_fake_embedder():
    assert isinstance(get_embedder(), FakeEmbedder)


def test_fastembed_rejects_unknown_model_without_downloading():
    with pytest.raises(ValueError):
        FastEmbedEmbedder("not/a-real-model")


def test_fastembed_knows_dimension_before_loading():
    embedder = FastEmbedEmbedder("BAAI/bge-small-en-v1.5")
    assert embedder.dimension == 384
    assert embedder._model is None  # nothing downloaded yet
