"""
Service for managing document and chunk persistence operations.

Decouples API route handlers from direct SQLAlchemy ORM querying.
"""

from typing import Optional, Sequence
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.document import Document, Chunk


def list_user_documents(session: Session, user_id: str) -> list[Document]:
    """List all documents owned by a specific user."""
    return session.query(Document).filter_by(user_id=user_id).all()


def get_user_document(session: Session, document_id: int, user_id: str) -> Optional[Document]:
    """Retrieve a single document owned by a user by ID."""
    return session.query(Document).filter_by(id=document_id, user_id=user_id).first()


def delete_user_document(session: Session, document_id: int, user_id: str) -> bool:
    """Delete a document owned by a user."""
    doc = get_user_document(session, document_id, user_id)
    if doc:
        session.delete(doc)
        session.flush()
        return True
    return False


def create_document_with_chunks(
    session: Session,
    user_id: str,
    title: str,
    content: str,
    chunk_contents: Sequence[str],
    sha256: Optional[str] = None,
    status: str = "completed",
) -> Document:
    """Create a Document and its associated Chunk entities in the database session."""
    doc = Document(
        user_id=user_id,
        title=title,
        content=content,
        sha256=sha256,
        status=status,
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

def mark_document_reviewed(db: Session, user: dict, document_id: int) -> Optional[Document]:
    """Mark a document as reviewed by updating the last_reviewed_at timestamp."""
    doc = get_user_document(db, document_id, user["username"])
    if doc:
        doc.last_reviewed_at = datetime.now(timezone.utc)
        db.commit()
        invalidate_staleness_cache()
    return doc
