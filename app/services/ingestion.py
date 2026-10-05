"""Document ingestion: upload, background indexing, re-indexing and deletion.

Upload does the cheap, user-facing part synchronously: it checks the file,
extracts and cleans its text, and stores it on the document with a form feed
between pages. Anything wrong with the file is reported immediately.

Indexing (chunk -> embed -> upsert into the vector store) runs afterwards via
`index_document`, which opens its own database session so it can run as a
FastAPI background task today and as a worker task later. Because the cleaned
pages are kept on the document, re-indexing never needs the original file.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Callable

from fastapi import BackgroundTasks
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.document import Chunk, Document
from app.services.chunking import chunk_text
from app.services import embedding_service
from app.services.embedding_service import EmbedderFactory, EmbeddingChoice, EmbeddingUnavailable
from app.services.embeddings import Embedder
from app.services.llm.base import ProviderError
from app.services.pdf_extraction import extract_pdf_pages
from app.services.text_cleaning import clean_text_pages
from app.services.token_estimation import estimate_token_count
from app.services.vector_store import ChunkVector, VectorStore

logger = logging.getLogger(__name__)

PAGE_SEPARATOR = "\f"
PDF_EXTENSIONS = {".pdf"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | TEXT_EXTENSIONS
EMBED_BATCH_SIZE = 64


class IngestionError(Exception):
    """A problem with the uploaded file that the user can fix."""


class UnsupportedFileError(IngestionError):
    pass


class FileTooLargeError(IngestionError):
    pass


class DuplicateDocumentError(IngestionError):
    def __init__(self, existing_id: int):
        super().__init__(f"This file was already uploaded as document {existing_id}")
        self.existing_id = existing_id


@dataclass(frozen=True)
class ExtractedPage:
    number: int
    text: str


def read_limited(stream: BinaryIO) -> bytes:
    """Read an upload, stopping one byte past the size limit instead of reading it all into memory."""
    limit = settings.max_upload_mb * 1024 * 1024
    content = stream.read(limit + 1)
    if len(content) > limit:
        raise FileTooLargeError(f"File is larger than {settings.max_upload_mb} MB")
    return content


def extract_pages(filename: str, content: bytes) -> list[ExtractedPage]:
    """Extract raw text per page. Text files are a single page."""
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Unsupported file type '{extension or filename}'. Upload one of: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    if extension in PDF_EXTENSIONS:
        try:
            pages = extract_pdf_pages(content)
        except Exception as exc:
            raise IngestionError(f"Failed to parse PDF: {exc}") from exc
        return [ExtractedPage(p["page_number"], p["text"]) for p in pages]
    return [ExtractedPage(1, content.decode("utf-8", errors="replace"))]


def _paginate(pages: list[ExtractedPage]) -> str:
    """Clean pages and join them so that position N holds page N+1 (blank pages kept)."""
    if not pages:
        return ""
    cleaned = clean_text_pages([p.text for p in pages])
    slots = [""] * max(p.number for p in pages)
    for page, text in zip(pages, cleaned):
        slots[page.number - 1] = text
    return PAGE_SEPARATOR.join(slots)


def create_document(
    session: Session,
    user_id: int,
    filename: str,
    content: bytes,
    group_id: int | None = None,
    pages: list[ExtractedPage] | None = None,
) -> Document:
    """Validate and store an uploaded file as a pending document. Call `index_document` next."""
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise FileTooLargeError(f"File is larger than {settings.max_upload_mb} MB")
    if not content:
        raise IngestionError("File is empty")

    sha256 = hashlib.sha256(content).hexdigest()
    existing = session.query(Document.id).filter(Document.user_id == user_id, Document.sha256 == sha256).first()
    if existing is not None:
        raise DuplicateDocumentError(existing.id)

    pages = pages if pages is not None else extract_pages(filename, content)
    text = _paginate(pages)
    if not text.replace(PAGE_SEPARATOR, "").strip():
        raise IngestionError("No text could be extracted from this file (is it a scanned PDF?)")

    document = Document(
        user_id=user_id,
        title=Path(filename).stem or filename,
        filename=filename,
        sha256=sha256,
        content=text,
        status="pending",
        index_updated_at=_now(),
        group_id=group_id,
    )
    session.add(document)
    session.flush()
    return document


def _build_chunks(document: Document) -> list[Chunk]:
    paged = document.filename is None or Path(document.filename).suffix.lower() in PDF_EXTENSIONS
    chunks: list[Chunk] = []
    for index, page_text in enumerate((document.content or "").split(PAGE_SEPARATOR), start=1):
        for piece in chunk_text(page_text, settings.chunk_window_size, settings.chunk_overlap_size):
            chunks.append(
                Chunk(
                    document_id=document.id,
                    content=piece,
                    sequence_order=len(chunks) + 1,
                    page_number=index if paged else None,
                    token_count=estimate_token_count(piece),
                )
            )
    return chunks


class _Superseded(Exception):
    """Another run claimed the document while this one was working."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _claim(session: Session, document_id: int, token: str) -> Document | None:
    """Make this run the document's owner; returns the document, or None if there is nothing to do.

    The newest run wins: a run that loses the claim notices before it commits
    (see index_document) and discards its work, so two runs for one document
    (Reindex during indexing, a stale job queued again) never leave duplicate
    chunks or orphaned vectors. A document that is already ready is left
    alone: that is a duplicate delivery of a job that has finished (Reindex
    sets the document back to pending first).
    """
    claimed = (
        session.query(Document)
        .filter(Document.id == document_id, Document.status != "ready")
        .update(
            {
                Document.status: "indexing",
                Document.error: None,
                Document.index_token: token,
                Document.index_updated_at: _now(),
            },
            synchronize_session=False,
        )
    )
    session.commit()
    return session.get(Document, document_id) if claimed else None


def index_document(
    document_id: int,
    session_factory: Callable[[], Session] = SessionLocal,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    embedder_factory: EmbedderFactory | None = None,
) -> None:
    """Chunk, embed and store a document's vectors, replacing any previous index.

    The document is embedded with its owner's embedding choice (see
    embedding_service), and records which model that was. `embedder` and
    `store` replace the local model and its store (tests); `embedder_factory`
    replaces how an embedder is built for the choice.

    Never raises: failures are recorded on the document as status "failed"
    with the error, because this usually runs after the response is sent or
    in a worker.

    Nothing outside the run's own work is touched until the run has proved it
    still owns the document: old chunks are replaced inside its transaction,
    and old vectors are removed only after it has committed.
    """
    token = str(uuid.uuid4())
    session = session_factory()
    new_chunk_ids: list[int] = []
    new_store: VectorStore | None = None
    used: Embedder | None = None
    user_id: int | None = None
    try:
        document = _claim(session, document_id, token)
        if document is None:
            return
        user_id = document.user_id
        try:
            # Where the current vectors are, before this run replaces them.
            old_store = embedding_service.document_store(document, local_store=store)
            if embedder is not None:
                choice = EmbeddingChoice(embedding_service.LOCAL, embedder.model_name)
                used = embedder
            else:
                choice = embedding_service.get_choice(session, user_id)
                used = (embedder_factory or embedding_service.build_embedder)(session, user_id, choice)

            chunks = _build_chunks(document)  # before any write, to keep the write transaction short
            old_chunk_ids = [cid for (cid,) in session.query(Chunk.id).filter(Chunk.document_id == document_id)]
            session.query(Chunk).filter(Chunk.document_id == document_id).delete(synchronize_session=False)
            session.add_all(chunks)
            session.flush()
            new_chunk_ids = [c.id for c in chunks]

            vectors: list[ChunkVector] = []
            for start in range(0, len(chunks), EMBED_BATCH_SIZE):
                batch = chunks[start:start + EMBED_BATCH_SIZE]
                embedded = used.embed_documents([c.content for c in batch])
                vectors.extend(ChunkVector(c.id, c.page_number, v) for c, v in zip(batch, embedded))
            # A provider's vector size is known once it has embedded something.
            new_store = embedding_service.store_for_choice(choice, used.dimension, local_store=store)
            if new_store is not None:
                new_store.upsert_document(user_id, document_id, vectors)

            # Finish only if this run still owns the document; the row lock this
            # takes makes a competing claim wait until we have committed.
            finished = (
                session.query(Document)
                .filter(Document.id == document_id, Document.index_token == token)
                .update(
                    {
                        Document.status: "ready",
                        Document.index_updated_at: _now(),
                        Document.embedding_provider: choice.provider,
                        Document.embedding_model: choice.model,
                        Document.embedding_dimension: used.dimension,
                    },
                    synchronize_session=False,
                )
            )
            if not finished:
                raise _Superseded()
            session.commit()
        except _Superseded:
            session.rollback()
            _discard_vectors(new_store, new_chunk_ids, document_id)
            logger.info("Index run superseded by a newer one", extra={"document_id": document_id})
            return
        except Exception as exc:
            session.rollback()
            _discard_vectors(new_store, new_chunk_ids, document_id)
            failed = (
                session.query(Document)
                .filter(Document.id == document_id, Document.index_token == token)
                .update(
                    {Document.status: "failed", Document.error: _failure_message(exc)},
                    synchronize_session=False,
                )
            )
            session.commit()
            if isinstance(exc, (EmbeddingUnavailable, ProviderError)):
                # The user's setting or their provider; the message says what to do.
                logger.warning("Indexing failed: %s", _failure_message(exc), extra={"document_id": document_id})
            elif failed:
                logger.exception("Indexing failed", extra={"document_id": document_id})
            else:
                # Deleted or taken over by a newer run meanwhile: nothing to report.
                logger.info("Indexing stopped; document deleted or re-queued", extra={"document_id": document_id})
            return
        # Committed: the old chunks are gone, so their vectors can go too.
        _discard_vectors(old_store, old_chunk_ids, document_id)
    finally:
        if used is not None and user_id is not None:
            _record_embedding_calls(session, user_id, used, document_id)
        session.close()


def _failure_message(exc: Exception) -> str:
    if isinstance(exc, EmbeddingUnavailable):
        return str(exc)[:1000]
    if isinstance(exc, ProviderError):
        return f"Embedding failed: {exc.message}"[:1000]
    return f"{type(exc).__name__}: {exc}"[:1000]


def _record_embedding_calls(session: Session, user_id: int, embedder: Embedder, document_id: int) -> None:
    try:
        embedding_service.record_calls(session, user_id, embedder)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Could not record embedding telemetry", extra={"document_id": document_id})


def _discard_vectors(store: VectorStore | None, chunk_ids: list[int], document_id: int) -> None:
    """Remove vectors whose chunk rows no longer exist. Leftovers are harmless
    (search ignores vectors without a chunk row), so a failure is only logged."""
    if store is None or not chunk_ids:
        return
    try:
        store.delete_points(chunk_ids)
    except Exception:
        logger.exception("Could not remove vectors of discarded chunks", extra={"document_id": document_id})


def schedule_indexing(document_id: int, background_tasks: BackgroundTasks | None = None) -> None:
    """Queue a document for indexing, after the caller has committed it.

    With TASK_QUEUE=celery the job goes to a worker through Redis; otherwise it
    runs in this process after the response (FastAPI background task). If the
    broker is unreachable the document is marked so the next sweep (see
    requeue_stalled) queues it again within minutes.
    """
    if settings.task_queue == "celery":
        from app.worker import index_document_task  # imported here: the worker imports this module

        try:
            index_document_task.delay(document_id)
        except Exception:
            logger.exception("Could not queue indexing; it will be retried", extra={"document_id": document_id})
            _mark_unqueued(document_id)
    elif background_tasks is not None:
        background_tasks.add_task(index_document, document_id)
    else:
        _run_inline([document_id])


def _mark_unqueued(document_id: int, session_factory: Callable[[], Session] = SessionLocal) -> None:
    # A NULL queue time counts as stale straight away.
    session = session_factory()
    try:
        session.query(Document).filter(Document.id == document_id, Document.status == "pending").update(
            {Document.index_updated_at: None}, synchronize_session=False
        )
        session.commit()
    except Exception:
        logger.exception("Could not mark document for re-queueing", extra={"document_id": document_id})
    finally:
        session.close()


def _run_inline(document_ids: list[int]) -> None:
    """Index documents one after another on a single background thread."""

    def run() -> None:
        for document_id in document_ids:
            index_document(document_id)

    threading.Thread(target=run, name="inline-indexing", daemon=True).start()


def _stale_condition(cutoff: datetime | None):
    """Documents whose job was lost: queued or indexing, and not touched since `cutoff`.

    A pending document with no queue time failed to reach the broker and is
    always stale. With cutoff None (an inline API starting up, so nothing of
    its own can still be running), every queued or indexing document is.
    """
    waiting = Document.status.in_(("pending", "indexing"))
    if cutoff is None:
        return waiting
    return and_(waiting, or_(Document.index_updated_at.is_(None), Document.index_updated_at < cutoff))


def stalled_documents(session: Session, now: datetime | None = None) -> list[int]:
    """Documents queued or indexing for longer than INDEX_STALE_MINUTES: their run was lost."""
    cutoff = (now or _now()) - timedelta(minutes=settings.index_stale_minutes)
    return [document_id for (document_id,) in session.query(Document.id).filter(_stale_condition(cutoff)).order_by(Document.id)]


def requeue_stalled(session_factory: Callable[[], Session] = SessionLocal, *, all_unfinished: bool = False) -> list[int]:
    """Queue stalled documents again; returns their ids.

    Each document is taken with a conditional update, so processes sweeping at
    the same time (several workers starting) never queue the same document
    twice. `all_unfinished` treats every queued or indexing document as lost,
    which is true only for an inline-mode API that is just starting.
    """
    cutoff = None if all_unfinished else _now() - timedelta(minutes=settings.index_stale_minutes)
    session = session_factory()
    taken: list[int] = []
    try:
        candidates = [d for (d,) in session.query(Document.id).filter(_stale_condition(cutoff)).order_by(Document.id)]
        for document_id in candidates:
            won = (
                session.query(Document)
                .filter(Document.id == document_id, _stale_condition(cutoff))
                .update({Document.index_updated_at: _now()}, synchronize_session=False)
            )
            session.commit()
            if won:
                taken.append(document_id)
    finally:
        session.close()
    if taken:
        logger.info("Re-queued stalled documents", extra={"count": len(taken)})
        if settings.task_queue == "celery":
            for document_id in taken:
                schedule_indexing(document_id)
        else:
            _run_inline(taken)
    return taken


def mark_for_reindex(session: Session, user_id: int, document_id: int) -> Document | None:
    document = session.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()
    if document is None:
        return None
    document.status = "pending"
    document.error = None
    document.index_updated_at = _now()
    session.flush()
    return document


def reindexable_document_ids(session: Session, user_id: int) -> list[int]:
    """The user's documents that have text to index again."""
    return [
        doc_id
        for (doc_id,) in session.query(Document.id)
        .filter(Document.user_id == user_id, Document.content.isnot(None))
        .order_by(Document.id)
    ]


def mark_documents_for_reindex(session: Session, user_id: int, document_ids: list[int]) -> list[int]:
    """mark_for_reindex for several documents; returns the ids that are the user's."""
    if not document_ids:
        return []
    documents = (
        session.query(Document)
        .filter(Document.user_id == user_id, Document.id.in_(document_ids), Document.content.isnot(None))
        .order_by(Document.id)
        .all()
    )
    for document in documents:
        document.status = "pending"
        document.error = None
        document.index_updated_at = _now()
    session.flush()
    return [d.id for d in documents]


STATUSES = ("pending", "indexing", "ready", "failed")


def batch_status(session: Session, user_id: int, document_ids: list[int] | None = None) -> dict:
    """Indexing status of the user's documents (or the given ones): counts and per-document detail."""
    query = session.query(Document.id, Document.title, Document.status, Document.error).filter(Document.user_id == user_id)
    if document_ids is not None:
        query = query.filter(Document.id.in_(document_ids))
    rows = query.order_by(Document.id).all()
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    queued = counts["pending"] + counts["indexing"]
    return {
        "status": "working" if queued else "idle",
        "queued": queued,
        "counts": counts,
        "documents": [
            {"id": r.id, "title": r.title, "status": r.status, "error": r.error} for r in rows
        ],
    }


def delete_document(session: Session, user_id: int, document_id: int, store: VectorStore | None = None) -> bool:
    """Delete a document, its chunks and its vectors."""
    document = session.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()
    if document is None:
        return False
    locations = embedding_service.vector_locations(session, user_id, [document_id], local_store=store)
    session.delete(document)
    session.flush()
    embedding_service.delete_vectors(user_id, locations)
    return True
