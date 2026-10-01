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
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.document import Chunk, Document
from app.services.chunking import chunk_text
from app.services.embeddings import Embedder, get_embedder
from app.services.pdf_extraction import extract_pdf_pages
from app.services.text_cleaning import clean_text_pages
from app.services.token_estimation import estimate_token_count
from app.services.vector_store import ChunkVector, VectorStore, get_vector_store

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


# One lock per document: a second run for the same document (Reindex clicked
# while the upload is still indexing) waits for the first, instead of both
# replacing the chunks at once and leaving duplicates or orphaned vectors.
# Indexing runs in this process, so a process-local lock covers it; a
# multi-process task queue would need a database lock instead.
_index_locks: dict[int, threading.Lock] = {}
_index_locks_guard = threading.Lock()


def _document_lock(document_id: int) -> threading.Lock:
    with _index_locks_guard:
        return _index_locks.setdefault(document_id, threading.Lock())


def index_document(
    document_id: int,
    session_factory: Callable[[], Session] = SessionLocal,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
) -> None:
    """Chunk, embed and store a document's vectors, replacing any previous index.

    Never raises: failures are recorded on the document as status "failed"
    with the error, because this usually runs after the response is sent.
    """
    with _document_lock(document_id):
        _index_document(document_id, session_factory, embedder, store)


def _index_document(
    document_id: int,
    session_factory: Callable[[], Session],
    embedder: Embedder | None,
    store: VectorStore | None,
) -> None:
    embedder = embedder or get_embedder()
    store = store or get_vector_store()
    session = session_factory()
    try:
        document = session.get(Document, document_id)
        if document is None:
            return
        user_id = document.user_id
        document.status = "indexing"
        document.error = None
        session.commit()

        try:
            store.delete_documents(user_id, [document.id])
            session.query(Chunk).filter(Chunk.document_id == document.id).delete(synchronize_session=False)
            chunks = _build_chunks(document)
            session.add_all(chunks)
            session.flush()

            vectors: list[ChunkVector] = []
            for start in range(0, len(chunks), EMBED_BATCH_SIZE):
                batch = chunks[start:start + EMBED_BATCH_SIZE]
                embedded = embedder.embed_documents([c.content for c in batch])
                vectors.extend(ChunkVector(c.id, c.page_number, v) for c, v in zip(batch, embedded))
            store.upsert_document(user_id, document.id, vectors)

            document.status = "ready"
            session.commit()
        except Exception as exc:
            session.rollback()
            # Vectors may have been written before the failure; the chunk rows
            # they point to were rolled back, so remove them.
            try:
                store.delete_documents(user_id, [document_id])
            except Exception:
                logger.exception("Could not clean up vectors after failed indexing", extra={"document_id": document_id})
            document = session.get(Document, document_id)
            if document is None:
                # Deleted while it was being indexed: nothing left to report on.
                logger.info("Document deleted during indexing", extra={"document_id": document_id})
                return
            logger.exception("Indexing failed", extra={"document_id": document_id})
            document.status = "failed"
            document.error = f"{type(exc).__name__}: {exc}"[:1000]
            session.commit()
    finally:
        session.close()


def mark_for_reindex(session: Session, user_id: int, document_id: int) -> Document | None:
    document = session.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()
    if document is None:
        return None
    document.status = "pending"
    document.error = None
    session.flush()
    return document


def delete_document(session: Session, user_id: int, document_id: int, store: VectorStore | None = None) -> bool:
    """Delete a document, its chunks and its vectors."""
    document = session.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()
    if document is None:
        return False
    session.delete(document)
    session.flush()
    (store or get_vector_store()).delete_documents(user_id, [document_id])
    return True
