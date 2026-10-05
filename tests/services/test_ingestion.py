import io
from datetime import datetime, timedelta, timezone
import threading
import time
import fitz
import pytest
from qdrant_client import QdrantClient, models
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.document import Chunk, Document
from app.services import ingestion
from app.services.embeddings import FakeEmbedder
from app.services.vector_store import VectorStore
from tests.helpers import make_user


def _pdf(*page_texts: str) -> bytes:
    pdf = fitz.open()
    for text in page_texts:
        page = pdf.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = pdf.tobytes()
    pdf.close()
    return data


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ingest.db'}")
    # Enforce foreign keys like the app's engine and PostgreSQL do: chunk
    # rows are removed by ON DELETE CASCADE when their document goes.
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    embedder = FakeEmbedder()
    store = VectorStore(QdrantClient(location=":memory:"), embedder.model_name, embedder.dimension)
    session = factory()
    user = make_user(session)
    session.commit()
    yield factory, session, user.id, embedder, store
    session.close()


def _index(env, document_id):
    factory, _, _, embedder, store = env
    ingestion.index_document(document_id, session_factory=factory, embedder=embedder, store=store)


def test_pdf_upload_keeps_page_numbers_including_blank_pages(env):
    _, session, user_id, _, store = env
    doc = ingestion.create_document(session, user_id, "handbook.pdf", _pdf("Intro page.", "", "Refunds take 30 days."))
    session.commit()
    assert doc.status == "pending"
    assert doc.title == "handbook"
    assert doc.content.split(ingestion.PAGE_SEPARATOR) == ["Intro page.", "", "Refunds take 30 days."]

    _index(env, doc.id)
    session.expire_all()
    doc = session.get(Document, doc.id)
    assert doc.status == "ready"
    chunks = sorted(doc.chunks, key=lambda c: c.sequence_order)
    assert [(c.page_number, c.content) for c in chunks] == [(1, "Intro page."), (3, "Refunds take 30 days.")]
    assert all(c.token_count for c in chunks)
    assert store.count(user_id, doc.id) == 2


def test_text_upload_has_no_page_numbers(env):
    _, session, user_id, _, _ = env
    doc = ingestion.create_document(session, user_id, "notes.md", b"# Notes\n\nShip on Friday.")
    session.commit()
    _index(env, doc.id)
    session.expire_all()
    assert {c.page_number for c in session.get(Document, doc.id).chunks} == {None}


def test_reindex_replaces_chunks_and_vectors(env):
    _, session, user_id, _, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"One sentence. Two sentence.")
    session.commit()
    _index(env, doc.id)
    _index(env, doc.id)
    session.expire_all()
    assert session.query(Chunk).filter(Chunk.document_id == doc.id).count() == store.count(user_id, doc.id)
    assert store.count(user_id, doc.id) >= 1


def test_indexing_failure_marks_document_failed(env):
    factory, session, user_id, embedder, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Some text.")
    session.commit()

    class BrokenEmbedder:
        model_name = embedder.model_name
        dimension = embedder.dimension

        def embed_documents(self, texts):
            raise RuntimeError("model crashed")

    ingestion.index_document(doc.id, session_factory=factory, embedder=BrokenEmbedder(), store=store)
    session.expire_all()
    doc = session.get(Document, doc.id)
    assert doc.status == "failed"
    assert "model crashed" in doc.error
    assert store.count(user_id, doc.id) == 0


def test_duplicate_upload_is_rejected_per_user(env):
    _, session, user_id, _, _ = env
    first = ingestion.create_document(session, user_id, "a.txt", b"Same bytes.")
    session.commit()
    with pytest.raises(ingestion.DuplicateDocumentError) as exc:
        ingestion.create_document(session, user_id, "b.txt", b"Same bytes.")
    assert exc.value.existing_id == first.id

    other = make_user(session)
    assert ingestion.create_document(session, other.id, "a.txt", b"Same bytes.").id != first.id


@pytest.mark.parametrize(
    "filename, content, error",
    [
        ("image.png", b"\x89PNG", ingestion.UnsupportedFileError),
        ("empty.txt", b"", ingestion.IngestionError),
        ("broken.pdf", b"%PDF-not really", ingestion.IngestionError),
        ("blank.pdf", _pdf(""), ingestion.IngestionError),
    ],
)
def test_bad_files_are_rejected_before_storing(env, filename, content, error):
    _, session, user_id, _, _ = env
    with pytest.raises(error):
        ingestion.create_document(session, user_id, filename, content)
    assert session.query(Document).count() == 0


def test_file_size_limit(env, monkeypatch):
    _, session, user_id, _, _ = env
    monkeypatch.setattr(ingestion.settings, "max_upload_mb", 0)
    with pytest.raises(ingestion.FileTooLargeError):
        ingestion.create_document(session, user_id, "a.txt", b"x")


def test_delete_document_removes_vectors(env):
    _, session, user_id, _, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Delete me.")
    session.commit()
    _index(env, doc.id)
    assert store.count(user_id, doc.id) == 1

    other = make_user(session)
    assert ingestion.delete_document(session, other.id, doc.id, store=store) is False
    assert ingestion.delete_document(session, user_id, doc.id, store=store) is True
    session.commit()
    assert store.count(user_id, doc.id) == 0
    assert session.query(Chunk).filter(Chunk.document_id == doc.id).count() == 0


def test_failure_after_vectors_were_written_removes_them(env):
    factory, session, user_id, embedder, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Some text.")
    session.commit()

    class StoreThatWritesThenFails:
        def __init__(self, inner):
            self.inner = inner

        def delete_documents(self, *args):
            return self.inner.delete_documents(*args)

        def upsert_document(self, *args):
            self.inner.upsert_document(*args)
            raise RuntimeError("connection dropped after write")

        def __getattr__(self, name):
            return getattr(self.inner, name)

    ingestion.index_document(doc.id, session_factory=factory, embedder=embedder, store=StoreThatWritesThenFails(store))
    session.expire_all()
    assert session.get(Document, doc.id).status == "failed"
    assert store.count(user_id, doc.id) == 0


def test_document_deleted_while_indexing_is_not_reported_as_failure(env, caplog):
    factory, session, user_id, embedder, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Some text.")
    session.commit()
    doc_id = doc.id

    class StoreRacingADelete:
        """Upsert fails (as the chunks' document row disappears) and the delete
        request commits before the indexer records the failure."""

        def __init__(self, inner):
            self.inner = inner

        def upsert_document(self, *args):
            raise RuntimeError("document vanished")

        def delete_points(self, chunk_ids):  # the cleanup after rollback
            other = factory()
            other.delete(other.get(Document, doc_id))
            other.commit()
            other.close()
            return self.inner.delete_points(chunk_ids)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    with caplog.at_level("INFO"):
        ingestion.index_document(doc_id, session_factory=factory, embedder=embedder, store=StoreRacingADelete(store))
    assert "document deleted or re-queued" in caplog.text
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    assert store.count(user_id, doc_id) == 0


class _CountingStream(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.requested = []

    def read(self, size=-1):
        self.requested.append(size)
        return super().read(size)


def test_read_limited_stops_just_past_the_limit(monkeypatch):
    monkeypatch.setattr(ingestion.settings, "max_upload_mb", 1)
    limit = 1024 * 1024
    assert ingestion.read_limited(io.BytesIO(b"x" * limit)) == b"x" * limit

    stream = _CountingStream(b"x" * (limit * 3))
    with pytest.raises(ingestion.FileTooLargeError):
        ingestion.read_limited(stream)
    # Never asked for the whole file.
    assert stream.requested == [limit + 1]


def _point_ids(store, user_id, document_id) -> set[int]:
    points, _ = store.client.scroll(
        store.collection,
        scroll_filter=models.Filter(must=[
            models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
            models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id)),
        ]),
        limit=1000,
    )
    return {int(p.id) for p in points}


def _chunk_ids(session, document_id) -> set[int]:
    return {c for (c,) in session.query(Chunk.id).filter(Chunk.document_id == document_id)}


def test_overlapping_runs_leave_exactly_the_newest_index(env, monkeypatch):
    """Reindex clicked while the upload is still indexing: the newer run wins and
    the older discards its work, so no duplicate chunks or orphaned vectors are left."""
    factory, session, user_id, embedder, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Alpha. Beta. Gamma.")
    session.commit()

    first_is_working = threading.Event()
    let_first_finish = threading.Event()
    build = ingestion._build_chunks

    def slow_first_build(document):
        if threading.current_thread().name == "first":
            first_is_working.set()
            let_first_finish.wait(5)
        return build(document)

    monkeypatch.setattr(ingestion, "_build_chunks", slow_first_build)

    def run():
        ingestion.index_document(doc.id, session_factory=factory, embedder=embedder, store=store)

    first = threading.Thread(target=run, name="first")
    first.start()
    first_is_working.wait(5)
    # Reindex: the document goes back to pending and a second run starts and finishes.
    ingestion.mark_for_reindex(session, user_id, doc.id)
    session.commit()
    second = threading.Thread(target=run, name="second")
    second.start()
    second.join(10)
    let_first_finish.set()
    first.join(10)

    session.expire_all()
    assert session.get(Document, doc.id).status == "ready"
    chunk_ids = _chunk_ids(session, doc.id)
    assert chunk_ids and _point_ids(store, user_id, doc.id) == chunk_ids


def test_a_superseded_run_discards_its_work_and_leaves_the_index_alone(env, monkeypatch):
    factory, session, user_id, embedder, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Alpha. Beta.")
    session.commit()
    _index(env, doc.id)
    session.expire_all()
    before = _chunk_ids(session, doc.id)
    assert _point_ids(store, user_id, doc.id) == before

    ingestion.mark_for_reindex(session, user_id, doc.id)
    session.commit()
    build = ingestion._build_chunks

    def taken_over(document):
        # Another run claims the document while this one is working.
        other = factory()
        other.query(Document).filter(Document.id == document.id).update({Document.index_token: "newer-run"})
        other.commit()
        other.close()
        return build(document)

    monkeypatch.setattr(ingestion, "_build_chunks", taken_over)
    ingestion.index_document(doc.id, session_factory=factory, embedder=embedder, store=store)
    session.expire_all()
    # Its chunks were rolled back and its vectors removed; the existing index is untouched.
    assert _chunk_ids(session, doc.id) == before
    assert _point_ids(store, user_id, doc.id) == before
    assert session.get(Document, doc.id).index_token == "newer-run"


def test_a_duplicate_delivery_of_a_finished_job_does_nothing(env):
    factory, session, user_id, embedder, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Alpha. Beta.")
    session.commit()
    _index(env, doc.id)
    session.expire_all()
    before = (_chunk_ids(session, doc.id), session.get(Document, doc.id).index_token)

    _index(env, doc.id)  # the same job again, e.g. redelivered by the broker
    session.expire_all()
    assert (_chunk_ids(session, doc.id), session.get(Document, doc.id).index_token) == before
    assert session.get(Document, doc.id).status == "ready"


def test_stalled_documents_are_found_and_requeued(env, monkeypatch):
    factory, session, user_id, _, _ = env
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=ingestion.settings.index_stale_minutes + 5)

    def doc(name, status, updated):
        d = Document(user_id=user_id, title=name, content="x", status=status, index_updated_at=updated)
        session.add(d)
        session.flush()
        return d.id

    stuck_pending = doc("a", "pending", old)
    stuck_indexing = doc("b", "indexing", old)
    never_queued = doc("c", "pending", None)  # the broker was down, or from before this column existed
    queued_now = doc("d", "pending", now)
    working_now = doc("e", "indexing", now)
    doc("f", "ready", old)
    doc("g", "failed", old)
    session.commit()

    assert ingestion.stalled_documents(session, now=now) == [stuck_pending, stuck_indexing, never_queued]

    ran = []
    monkeypatch.setattr(ingestion, "_run_inline", lambda ids: ran.extend(ids))
    assert ingestion.requeue_stalled(factory) == [stuck_pending, stuck_indexing, never_queued]
    assert ran == [stuck_pending, stuck_indexing, never_queued]
    # Taken: another sweep (e.g. a second worker starting) finds nothing more to queue.
    assert ingestion.requeue_stalled(factory) == []

    # An inline API that is starting up owns no running jobs, so every unfinished document was interrupted.
    ran.clear()
    assert ingestion.requeue_stalled(factory, all_unfinished=True) == [stuck_pending, stuck_indexing, never_queued, queued_now, working_now]


def test_requeued_documents_go_to_celery_when_configured(env, monkeypatch):
    factory, session, user_id, _, _ = env
    session.add(Document(user_id=user_id, title="lost", content="x", status="pending", index_updated_at=None))
    session.commit()
    scheduled = []
    monkeypatch.setattr(ingestion.settings, "task_queue", "celery")
    monkeypatch.setattr(ingestion, "schedule_indexing", lambda document_id, background_tasks=None: scheduled.append(document_id))
    assert ingestion.requeue_stalled(factory) == scheduled != []


def test_schedule_indexing_sends_jobs_to_celery_when_configured(monkeypatch, caplog):
    from app import worker

    sent = []
    monkeypatch.setattr(ingestion.settings, "task_queue", "celery")
    monkeypatch.setattr(worker.index_document_task, "delay", lambda document_id: sent.append(document_id))
    ingestion.schedule_indexing(7)
    assert sent == [7]

    def broker_down(document_id):
        raise ConnectionError("redis is down")

    marked = []
    monkeypatch.setattr(worker.index_document_task, "delay", broker_down)
    monkeypatch.setattr(ingestion, "_mark_unqueued", lambda document_id: marked.append(document_id))
    with caplog.at_level("ERROR"):
        ingestion.schedule_indexing(8)  # does not raise: the next sweep queues it again
    assert "Could not queue indexing" in caplog.text
    assert marked == [8]


def test_a_document_that_never_reached_the_broker_is_stale_at_once(env):
    factory, session, user_id, _, _ = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Text.")
    session.commit()
    assert ingestion.stalled_documents(session) == []
    ingestion._mark_unqueued(doc.id, factory)
    session.expire_all()
    assert ingestion.stalled_documents(session) == [doc.id]


def test_batch_status_counts_and_lists_the_users_documents(env):
    _, session, user_id, _, _ = env
    for name, status in [("a", "ready"), ("b", "pending"), ("c", "failed"), ("d", "indexing")]:
        session.add(Document(user_id=user_id, title=name, content="x", status=status, error="boom" if status == "failed" else None))
    session.add(Document(user_id=make_user(session).id, title="other", content="x", status="pending"))
    session.commit()

    result = ingestion.batch_status(session, user_id)
    assert result["counts"] == {"pending": 1, "indexing": 1, "ready": 1, "failed": 1}
    assert (result["status"], result["queued"]) == ("working", 2)
    assert [d["title"] for d in result["documents"]] == ["a", "b", "c", "d"]
    assert result["documents"][2]["error"] == "boom"

    only_ready = ingestion.batch_status(session, user_id, [result["documents"][0]["id"]])
    assert (only_ready["status"], only_ready["queued"]) == ("idle", 0)


# ---------------------------------------------------------------- embedding choice


def _choose(session, user_id, provider, model=None):
    from app.services import embedding_service
    from tests.fakes import provider_embedder_factory

    embedding_service.save_choice(session, user_id, provider, model, factory=provider_embedder_factory())
    session.commit()


def _index_with_choice(env, document_id, factory):
    session_factory, _, _, _, store = env
    ingestion.index_document(document_id, session_factory=session_factory, store=store, embedder_factory=factory)


def test_a_document_is_embedded_with_its_owners_choice_and_records_it(env, vector_stores):
    from app.models.telemetry_event import TelemetryEvent
    from app.services import vector_store
    from tests.fakes import provider_embedder_factory

    _, session, user_id, _, local_store = env
    _choose(session, user_id, "openai")
    doc = ingestion.create_document(session, user_id, "notes.md", b"Ship on Friday.\n\nReview on Monday.")
    session.commit()

    factory = provider_embedder_factory()
    _index_with_choice(env, doc.id, factory)
    session.expire_all()
    doc = session.get(Document, doc.id)

    assert doc.status == "ready"
    assert (doc.embedding_provider, doc.embedding_model, doc.embedding_dimension) == ("openai", "text-embedding-3-small", 64)
    remote = vector_store.store_for("openai/text-embedding-3-small", 64)
    assert remote.count(user_id, doc.id) == len(doc.chunks)
    assert local_store.count(user_id, doc.id) == 0
    # The provider calls are in telemetry (the settings check, then indexing).
    assert session.query(TelemetryEvent).filter_by(operation="embedding").count() == 2


def test_switching_models_moves_the_vectors_to_the_new_collection(env, vector_stores):
    from app.services import vector_store
    from tests.fakes import provider_embedder_factory

    _, session, user_id, _, local_store = env
    doc = ingestion.create_document(session, user_id, "notes.md", b"Ship on Friday.")
    session.commit()
    _index(env, doc.id)  # the local model
    assert local_store.count(user_id, doc.id) == 1

    _choose(session, user_id, "mistral")
    ingestion.mark_for_reindex(session, user_id, doc.id)
    session.commit()
    _index_with_choice(env, doc.id, provider_embedder_factory())

    remote = vector_store.store_for("mistral/mistral-embed", 64)
    assert remote.count(user_id, doc.id) == 1
    assert local_store.count(user_id, doc.id) == 0

    # Deleting the document removes the vectors from the collection they are in.
    assert ingestion.delete_document(session, user_id, doc.id, store=local_store)
    session.commit()
    assert remote.count(user_id, doc.id) == 0


def test_an_unusable_embedding_choice_fails_with_a_readable_message(env, vector_stores):
    from app.services.llm import ProviderError
    from tests.fakes import provider_embedder_factory

    _, session, user_id, _, local_store = env
    _choose(session, user_id, "openai")
    doc = ingestion.create_document(session, user_id, "notes.md", b"Ship on Friday.")
    session.commit()

    # The real factory: the user never stored an OpenAI key.
    _index_with_choice(env, doc.id, None)
    session.expire_all()
    doc = session.get(Document, doc.id)
    assert doc.status == "failed"
    assert doc.error.startswith("No API key stored for OpenAI, which your embedding setting uses.")
    assert "sk-" not in doc.error

    ingestion.mark_for_reindex(session, user_id, doc.id)
    session.commit()
    _index_with_choice(env, doc.id, provider_embedder_factory(fail=ProviderError("OpenAI returned HTTP 429: slow down", 429)))
    session.expire_all()
    doc = session.get(Document, doc.id)
    assert (doc.status, doc.error) == ("failed", "Embedding failed: OpenAI returned HTTP 429: slow down")
    assert session.query(Chunk).filter_by(document_id=doc.id).count() == 0


def test_mark_documents_for_reindex_only_touches_the_users_documents(env):
    _, session, user_id, _, _ = env
    mine = ingestion.create_document(session, user_id, "a.md", b"Alpha.")
    other_user = make_user(session)
    theirs = ingestion.create_document(session, other_user.id, "b.md", b"Beta.")
    mine.status = theirs.status = "ready"
    session.commit()

    assert ingestion.reindexable_document_ids(session, user_id) == [mine.id]
    assert ingestion.mark_documents_for_reindex(session, user_id, [mine.id, theirs.id]) == [mine.id]
    assert (mine.status, theirs.status) == ("pending", "ready")
