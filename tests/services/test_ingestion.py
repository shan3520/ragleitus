import fitz
import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
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
