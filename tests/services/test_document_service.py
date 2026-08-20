import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.evaluation import Base
from app.services.document_service import (
    create_document_with_chunks,
    list_user_documents,
    get_user_document,
    delete_user_document,
)


def _setup_in_memory_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_document_service_crud_flow():
    session = _setup_in_memory_db()

    # Create document
    doc = create_document_with_chunks(
        session=session,
        user_id="user1",
        title="Test PDF Document",
        content="Full text content",
        chunk_contents=["Chunk 1 content", "Chunk 2 content"],
        sha256="abc123hash",
    )
    session.commit()

    assert doc.id is not None
    assert doc.user_id == "user1"
    assert doc.title == "Test PDF Document"
    assert len(doc.chunks) == 2
    assert doc.chunks[0].sequence_order == 1

    # List documents
    user1_docs = list_user_documents(session, "user1")
    assert len(user1_docs) == 1
    assert user1_docs[0].id == doc.id

    user2_docs = list_user_documents(session, "user2")
    assert len(user2_docs) == 0

    # Get document
    retrieved = get_user_document(session, doc.id, "user1")
    assert retrieved is not None
    assert retrieved.id == doc.id

    non_retrieved = get_user_document(session, doc.id, "user2")
    assert non_retrieved is None

    # Delete document
    deleted = delete_user_document(session, doc.id, "user1")
    session.commit()
    assert deleted is True

    assert get_user_document(session, doc.id, "user1") is None
    assert delete_user_document(session, doc.id, "user1") is False


def test_mark_document_reviewed():
    from app.services.document_service import mark_document_reviewed
    session = _setup_in_memory_db()

    doc = create_document_with_chunks(
        session=session,
        user_id="review_user",
        title="Review Document",
        content="Full text content",
        chunk_contents=[],
        sha256="abc123hash",
    )
    session.commit()

    # User dict required by the service signature
    user_dict = {"username": "review_user"}

    # Initial state
    assert doc.last_reviewed_at is None

    # Mark as reviewed
    reviewed_doc = mark_document_reviewed(session, user_dict, doc.id)
    assert reviewed_doc is not None
    assert reviewed_doc.id == doc.id
    assert reviewed_doc.last_reviewed_at is not None

    # Try with wrong user
    wrong_user_dict = {"username": "wrong_user"}
    non_doc = mark_document_reviewed(session, wrong_user_dict, doc.id)
    assert non_doc is None
