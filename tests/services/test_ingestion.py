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


class _StallingStore:
    """Wraps a VectorStore and stalls the first run right after it clears the old vectors."""

    def __init__(self, store):
        self._store = store
        self.stalled = threading.Event()
        self.upserts: list[str] = []
        self._deletes = 0

    def delete_documents(self, user_id, document_ids):
        self._store.delete_documents(user_id, document_ids)
        self._deletes += 1
        if self._deletes == 1:
            self.stalled.set()
            time.sleep(0.5)

    def upsert_document(self, user_id, document_id, vectors):
        self._store.upsert_document(user_id, document_id, vectors)
        self.upserts.append(threading.current_thread().name)

    def __getattr__(self, name):
        return getattr(self._store, name)


def test_overlapping_runs_leave_exactly_the_newest_index(env):
    """Two runs at once (Reindex clicked while the upload is still indexing, or a
    job delivered to two workers): the newer run wins and the older discards its
    work, so no duplicate chunks or orphaned vectors are left."""
    factory, session, user_id, embedder, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Alpha. Beta. Gamma.")
    session.commit()
    stalling = _StallingStore(store)

    def run():
        ingestion.index_document(doc.id, session_factory=factory, embedder=embedder, store=stalling)

    first = threading.Thread(target=run, name="first")
    first.start()
    stalling.stalled.wait(5)
    second = threading.Thread(target=run, name="second")
    second.start()
    first.join(10)
    second.join(10)

    session.expire_all()
    assert session.get(Document, doc.id).status == "ready"
    chunk_ids = _chunk_ids(session, doc.id)
    assert chunk_ids and _point_ids(store, user_id, doc.id) == chunk_ids
    assert "second" in stalling.upserts


def test_a_superseded_run_discards_its_chunks_and_vectors(env):
    factory, session, user_id, embedder, store = env
    doc = ingestion.create_document(session, user_id, "a.txt", b"Alpha. Beta.")
    session.commit()
    _index(env, doc.id)
    session.expire_all()
    before = _chunk_ids(session, doc.id)

    class TakenOverWhileWorking:
        """Another run claims the document after this one started. (Simulated just
        before this run writes, as SQLite lets only one writer in at a time.)"""

        def __init__(self, inner):
            self.inner = inner

        def delete_documents(self, *args):
            self.inner.delete_documents(*args)
            other = factory()
            other.query(Document).filter(Document.id == doc.id).update({Document.index_token: "newer-run"})
            other.commit()
            other.close()

        def __getattr__(self, name):
            return getattr(self.inner, name)

    ingestion.index_document(doc.id, session_factory=factory, embedder=embedder, store=TakenOverWhileWorking(store))
    session.expire_all()
    # The superseded run's chunks were rolled back and its vectors removed; it did not mark the document ready.
    assert _chunk_ids(session, doc.id) == before
    assert _point_ids(store, user_id, doc.id) == set()  # old vectors were cleared by the run; the newer run rebuilds them
    assert session.get(Document, doc.id).index_token == "newer-run"


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
    legacy = doc("c", "indexing", None)  # from before this column existed
    doc("d", "pending", now)  # just queued
    doc("e", "ready", old)
    doc("f", "failed", old)
    session.commit()

    assert ingestion.stalled_documents(session, now=now) == [stuck_pending, stuck_indexing, legacy]

    scheduled = []
    monkeypatch.setattr(ingestion, "schedule_indexing", lambda document_id, background_tasks=None: scheduled.append(document_id))
    assert ingestion.requeue_stalled(factory) == [stuck_pending, stuck_indexing, legacy]
    assert scheduled == [stuck_pending, stuck_indexing, legacy]
    # Re-queued documents are not picked up again until they go stale once more.
    session.expire_all()
    assert ingestion.stalled_documents(session) == []


def test_schedule_indexing_sends_jobs_to_celery_when_configured(monkeypatch, caplog):
    from app import worker

    sent = []
    monkeypatch.setattr(ingestion.settings, "task_queue", "celery")
    monkeypatch.setattr(worker.index_document_task, "delay", lambda document_id: sent.append(document_id))
    ingestion.schedule_indexing(7)
    assert sent == [7]

    def broker_down(document_id):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(worker.index_document_task, "delay", broker_down)
    with caplog.at_level("ERROR"):
        ingestion.schedule_indexing(8)  # does not raise: stale-job recovery retries it
    assert "Could not queue indexing" in caplog.text


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
