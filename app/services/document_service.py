"""
Service for managing document and chunk persistence operations.

Decouples API route handlers from direct SQLAlchemy ORM querying.
"""

from typing import Optional, Sequence
from datetime import datetime, timezone
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.document import Document, Chunk
from app.models.feedback import SearchFeedback


def list_user_documents(session: Session, user_id: int) -> list[Document]:
    """List all documents owned by a specific user.

    Each document is fetched together with its aggregated statistics (the
    count of negative feedback records) in a single query: a LEFT OUTER JOIN
    over the related feedback records with GROUP BY, so documents with no
    related records are still returned with a stat of 0 and callers need no
    per-document follow-up queries.
    """
    rows = (
        session.query(
            Document,
            func.count(
                case((SearchFeedback.is_positive == False, SearchFeedback.id))
            ).label("negative_impact"),
        )
        .outerjoin(Document.feedbacks)
        .filter(Document.user_id == user_id)
        .group_by(Document.id)
        .all()
    )
    documents = []
    for document, negative_count in rows:
        document.negative_impact = float(negative_count or 0)
        documents.append(document)
    return documents


def get_user_document(session: Session, document_id: int, user_id: int) -> Optional[Document]:
    """Retrieve a single document owned by a user by ID."""
    return session.query(Document).filter_by(id=document_id, user_id=user_id).first()


def delete_user_document(session: Session, document_id: int, user_id: int) -> bool:
    """Delete a document owned by a user."""
    doc = get_user_document(session, document_id, user_id)
    if doc:
        session.delete(doc)
        session.flush()
        return True
    return False


def create_document_with_chunks(
    session: Session,
    user_id: int,
    title: str,
    content: str,
    chunk_contents: Sequence[str],
    sha256: Optional[str] = None,
    status: str = "completed",
    group_id: Optional[int] = None,
) -> Document:
    """Create a Document and its associated Chunk entities in the database session."""
    doc = Document(
        user_id=user_id,
        title=title,
        content=content,
        sha256=sha256,
        status=status,
        group_id=group_id,
    )
    session.add(doc)
    session.flush()

    for idx, chunk_text in enumerate(chunk_contents, start=1):
        chunk = Chunk(
            document_id=doc.id,
            content=chunk_text,
            sequence_order=idx,
        )
        session.add(chunk)

    session.flush()
    return doc


from app.services.staleness_scoring import invalidate_staleness_cache

def mark_document_reviewed(db: Session, user_id: int, document_id: int) -> Optional[Document]:
    """Mark a document as reviewed by updating the last_reviewed_at timestamp."""
    doc = get_user_document(db, document_id, user_id)
    if doc:
        doc.last_reviewed_at = datetime.now(timezone.utc)
        db.commit()
        invalidate_staleness_cache()
    return doc
