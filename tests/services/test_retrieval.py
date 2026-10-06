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

    def add_with(user_id, filename, text, embedder_factory):
        """Index with the user's embedding choice through a fake provider."""
        doc = ingestion.create_document(session, user_id, filename, text.encode())
        session.commit()
        ingestion.index_document(doc.id, session_factory=factory, store=store, embedder_factory=embedder_factory)
        session.expire_all()
        return doc.id

    add.with_choice = add_with

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


def test_does_not_embed_the_query_without_ready_documents(env):
    session, add, search = env
    user = make_user(session)
    session.commit()

    class Unavailable:
        def embed_query(self, text):
            raise AssertionError("embedded a query with nothing to search")

    assert retrieve(session, user.id, "anything", embedder=Unavailable(), store=search.store) == []


def _choose(session, user_id, provider):
    from app.services import embedding_service
    from tests.fakes import provider_embedder_factory

    embedding_service.save_choice(session, user_id, provider, None, factory=provider_embedder_factory())
    session.commit()


def test_documents_embedded_with_different_models_are_all_searched(env, vector_stores):
    from tests.fakes import provider_embedder_factory

    session, add, search = env
    user = make_user(session)
    session.commit()
    local_doc = add(user.id, "hr.txt", "Employees receive 25 days of annual leave.")
    _choose(session, user.id, "openai")
    factory = provider_embedder_factory()
    remote_doc = add.with_choice(user.id, "it.txt", "Passwords must be rotated every 90 days.", factory)

    leave = search(user.id, "annual leave days", embedder_factory=factory)
    passwords = search(user.id, "how often are passwords rotated", embedder_factory=factory)

    assert leave[0].document_id == local_doc and leave[0].dense_rank == 1
    assert passwords[0].document_id == remote_doc and passwords[0].dense_rank == 1
    # Each provider call is in telemetry: the settings check, indexing, and one
    # question embedding per search.
    from app.models.telemetry_event import TelemetryEvent

    assert session.query(TelemetryEvent).filter_by(operation="embedding").count() == 4


def test_a_provider_that_cannot_be_used_falls_back_to_keywords_with_a_warning(env, vector_stores):
    from app.services.llm import ProviderError
    from tests.fakes import provider_embedder_factory

    session, add, search = env
    user = make_user(session)
    session.commit()
    _choose(session, user.id, "openai")
    doc = add.with_choice(user.id, "it.txt", "Passwords must be rotated every 90 days.", provider_embedder_factory())

    warnings: list[str] = []
    down = provider_embedder_factory(fail=ProviderError("OpenAI returned HTTP 503: overloaded", 503))
    results = search(user.id, "passwords rotated", embedder_factory=down, warnings=warnings)
    assert [r.document_id for r in results] == [doc]
    assert results[0].dense_rank is None and results[0].keyword_rank == 1
    assert warnings == [
        "1 document embedded with openai/text-embedding-3-small could only be searched by keyword: "
        "OpenAI returned HTTP 503: overloaded"
    ]

    # The real factory: no key stored for OpenAI.
    warnings.clear()
    assert search(user.id, "passwords rotated", warnings=warnings)
    assert "No API key stored for OpenAI" in warnings[0]


def test_dense_or_keyword_strategies_use_one_ranking(env):
    session, add, search = env
    user = make_user(session)
    session.commit()
    add(user.id, "errors.txt", "Error E-4711 means the upstream certificate expired.")
    add(user.id, "hr.txt", "Employees receive 25 days of annual leave.")

    keyword = search(user.id, "E-4711", strategy="keyword")
    assert keyword and all(r.dense_rank is None and r.keyword_rank for r in keyword)
    dense = search(user.id, "annual leave", strategy="dense")
    assert dense and all(r.keyword_rank is None and r.dense_rank for r in dense)
    with pytest.raises(ValueError):
        search(user.id, "x", strategy="magic")


# ---------------------------------------------------------------- reranking


class _ScriptedReranker:
    """Puts the passages containing `favourite` first; records what it was asked."""

    model_name = "scripted"
    provider = "together"
    model = "scripted-rank"

    def __init__(self, favourite="", fail=None):
        self.favourite, self.fail = favourite, fail
        self.asked: list[tuple[str, list[str]]] = []
        self.calls = []

    def rerank(self, query, passages):
        self.asked.append((query, passages))
        if self.fail:
            raise self.fail
        return [1.0 if self.favourite in p else 0.0 for p in passages]


def _turn_on_reranking(session, user_id, provider="local"):
    from app.models.user_settings import UserSettings

    session.merge(UserSettings(user_id=user_id, rerank_provider=provider, rerank_model=None if provider == "local" else "m"))
    session.commit()


def _many(add, user_id):
    for i in range(10):
        add(user_id, f"leave{i}.txt", f"Annual leave policy note {i}: employees receive leave days.")
    add(user_id, "travel.txt", "Travel policy: annual leave days can be combined with travel.")


def test_reranking_reorders_the_candidates_and_keeps_the_top_k(env):
    session, add, search = env
    user = make_user(session)
    session.commit()
    _many(add, user.id)
    _turn_on_reranking(session, user.id)
    reranker = _ScriptedReranker(favourite="Travel policy")

    results = search(user.id, "annual leave days", k=3, reranker_factory=lambda s, u, c: reranker)

    assert len(results) == 3
    assert results[0].document_title == "travel" and results[0].rerank_score == 1.0
    query, passages = reranker.asked[0]
    assert query == "annual leave days" and len(passages) == 11  # every candidate, not just the top 3
    # Without reranking (setting off, or turned off for the call) the order is the fused one.
    assert all(r.rerank_score is None for r in search(user.id, "annual leave days", k=3, rerank=False))


def test_reranking_is_off_unless_the_user_turned_it_on(env):
    session, add, search = env
    user = make_user(session)
    session.commit()
    _many(add, user.id)
    reranker = _ScriptedReranker(favourite="Travel policy")

    results = search(user.id, "annual leave days", k=3, reranker_factory=lambda s, u, c: reranker)
    assert reranker.asked == [] and all(r.rerank_score is None for r in results)

    # Asked for explicitly (an experiment variant) while off: a warning, the usual order.
    warnings = []
    search(user.id, "annual leave days", k=3, rerank=True, warnings=warnings, reranker_factory=lambda s, u, c: reranker)
    assert reranker.asked == [] and "it is off in your settings" in warnings[0]


def test_a_failing_reranker_keeps_the_fused_order_with_a_warning(env):
    from app.services.llm import ProviderError
    from app.services.reranking import RerankUnavailable

    session, add, search = env
    user = make_user(session)
    session.commit()
    _many(add, user.id)
    plain = search(user.id, "annual leave days", k=3)
    _turn_on_reranking(session, user.id, provider="together")

    for failure, reason in [
        (ProviderError("Together AI returned HTTP 503: overloaded", 503), "Together AI returned HTTP 503: overloaded"),
        (RuntimeError("model file corrupt"), "RuntimeError"),
    ]:
        warnings = []
        reranker = _ScriptedReranker(fail=failure)
        results = search(user.id, "annual leave days", k=3, warnings=warnings, reranker_factory=lambda s, u, c: reranker)
        assert [r.chunk_id for r in results] == [r.chunk_id for r in plain]
        assert warnings == [
            f"Passages could not be reranked with together/m, so they are in their usual order: {reason}"
        ]

    def no_key(session_, user_id, choice):
        raise RerankUnavailable("No API key stored for Together AI, which your reranking setting uses.")

    warnings = []
    assert len(search(user.id, "annual leave days", k=3, warnings=warnings, reranker_factory=no_key)) == 3
    assert "No API key stored for Together AI" in warnings[0]


def test_the_local_reranker_is_used_by_default_when_on(env):
    session, add, search = env
    user = make_user(session)
    session.commit()
    add(user.id, "errors.txt", "Error E-4711 means the upstream certificate expired.")
    add(user.id, "hr.txt", "Employees receive 25 days of annual leave.")
    _turn_on_reranking(session, user.id)

    results = search(user.id, "What does error E-4711 mean?")  # the fake local reranker (shared words)
    assert results[0].document_title == "errors" and results[0].rerank_score > results[-1].rerank_score
