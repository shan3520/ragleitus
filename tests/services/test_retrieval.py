import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.document import Document
from app.services import ingestion
from app.services.embeddings import FakeEmbedder
from app.services.retrieval import retrieve
from app.services.vector_store import ChunkVector, VectorStore
from tests.helpers import make_user
from tests.postgres import fresh_postgres, needs_postgres


@pytest.fixture(params=["sqlite", pytest.param("postgresql", marks=needs_postgres)])
def env(request, tmp_path):
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'retrieval.db'}")
        Base.metadata.create_all(engine)
    else:
        engine = fresh_postgres()
    factory = sessionmaker(bind=engine)
    embedder = FakeEmbedder()
    store = VectorStore(QdrantClient(location=":memory:"), embedder.model_name, embedder.dimension)
    session = factory()

    def add(user_id, filename, text):
        doc = ingestion.create_document(session, user_id, filename, text.encode())
        session.commit()
        ingestion.index_document(doc.id, session_factory=factory, embedder=embedder, store=store)
        session.expire_all()
        return doc.id

    def search(user_id, query, **kwargs):
        return retrieve(session, user_id, query, embedder=embedder, store=store, **kwargs)

    search.store, search.embedder = store, embedder

    yield session, add, search
    session.close()
    engine.dispose()


def test_finds_the_relevant_passage_and_its_source(env):
    session, add, search = env
    user = make_user(session)
    session.commit()
    add(user.id, "hr.txt", "Employees receive 25 days of annual leave.")
    add(user.id, "it.txt", "Passwords must be rotated every 90 days.")

    results = search(user.id, "how many days of annual leave")
    assert results[0].document_title == "hr"
    assert "25 days" in results[0].content
    assert results[0].dense_rank is not None and results[0].keyword_rank is not None


def test_keyword_search_catches_exact_codes(env):
    session, add, search = env
    user = make_user(session)
    session.commit()
    add(user.id, "errors.txt", "Error E-4711 means the upstream certificate expired.")
    add(user.id, "other.txt", "Unrelated text about lunch menus and parking.")

    assert search(user.id, "E-4711")[0].document_title == "errors"


def test_never_returns_another_users_chunks(env):
    session, add, search = env
    alice, bob = make_user(session), make_user(session)
    session.commit()
    add(alice.id, "secret.txt", "The merger closes on March 3rd.")

    assert search(bob.id, "when does the merger close") == []
    assert search(alice.id, "when does the merger close")


def test_skips_documents_that_are_not_ready_and_honours_document_filter(env):
    session, add, search = env
    user = make_user(session)
    session.commit()
    first = add(user.id, "a.txt", "Apples are red.")
    second = add(user.id, "b.txt", "Apples are also green.")

    assert {r.document_id for r in search(user.id, "apples", document_ids=[second])} == {second}

    session.get(Document, first).status = "indexing"
    session.commit()
    assert {r.document_id for r in search(user.id, "apples")} == {second}


def test_limits_results_and_handles_empty_input(env):
    session, add, search = env
    user = make_user(session)
    session.commit()
    for i in range(5):
        add(user.id, f"{i}.txt", f"Fact number {i} about rockets.")

    assert len(search(user.id, "rockets", k=3)) == 3
    assert search(user.id, "   ") == []
    other = make_user(session)
    assert search(other.id, "rockets") == []


def test_ignores_vectors_whose_chunk_is_gone(env):
    session, add, search = env
    user = make_user(session)
    session.commit()
    doc_id = add(user.id, "a.txt", "Rockets fly high.")
    store = search.store
    store.upsert_document(
        user.id, doc_id, [ChunkVector(chunk_id=987654, page_number=None, vector=search.embedder.embed_query("Rockets"))]
    )

    assert 987654 not in {r.chunk_id for r in search(user.id, "rockets")}
    assert search(user.id, "rockets")


def test_reads_only_the_chunks_it_returns_on_postgres(env):
    session, add, search = env
    if session.get_bind().dialect.name != "postgresql":
        pytest.skip("SQLite scores keywords in memory, which reads every chunk")
    user = make_user(session)
    session.commit()
    add(user.id, "big.txt", "\n\n".join(f"Routine paragraph {i} about lunch menus." for i in range(200)))
    add(user.id, "errors.txt", "Error E-4711 means the upstream certificate expired.")

    statements = []
    listen = lambda conn, cursor, statement, *args: statements.append(statement)  # noqa: E731
    event.listen(session.get_bind(), "before_cursor_execute", listen)
    try:
        results = search(user.id, "what does E-4711 mean", k=2)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", listen)

    assert results[0].document_title == "errors"
    reads_text = [s for s in statements if "chunks.content" in s]
    assert reads_text and all("chunks.id IN" in s for s in reads_text), reads_text
