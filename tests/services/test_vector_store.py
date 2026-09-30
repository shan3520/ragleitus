from qdrant_client import QdrantClient

from app.services.embeddings import FakeEmbedder
from app.services.vector_store import ChunkVector, VectorStore


def _store():
    return VectorStore(QdrantClient(location=":memory:"), "fake-hash", 256)


def test_collection_name_encodes_model_and_dimension():
    assert _store().collection == "chunks_fake_hash_256"


def test_search_is_scoped_to_user_and_documents():
    store = _store()
    embedder = FakeEmbedder()
    text = "vacation policy days"
    vector = embedder.embed_query(text)
    store.upsert_document(1, 10, [ChunkVector(100, 1, vector)])
    store.upsert_document(1, 11, [ChunkVector(101, 2, vector)])
    store.upsert_document(2, 20, [ChunkVector(200, 1, vector)])

    hits = store.search(1, vector, limit=10)
    assert {h.chunk_id for h in hits} == {100, 101}
    assert {h.chunk_id for h in store.search(1, vector, limit=10, document_ids=[11])} == {101}
    assert {h.chunk_id for h in store.search(2, vector, limit=10)} == {200}


def test_delete_documents_only_touches_the_owner():
    store = _store()
    vector = FakeEmbedder().embed_query("x")
    store.upsert_document(1, 10, [ChunkVector(100, None, vector)])
    store.upsert_document(2, 10, [ChunkVector(200, None, vector)])  # same document id, other user

    store.delete_documents(2, [10])
    assert store.count(1) == 1
    assert store.count(2) == 0


def test_upsert_with_same_chunk_ids_does_not_duplicate():
    store = _store()
    vector = FakeEmbedder().embed_query("x")
    store.upsert_document(1, 10, [ChunkVector(100, 1, vector)])
    store.upsert_document(1, 10, [ChunkVector(100, 1, vector)])
    assert store.count(1, 10) == 1
