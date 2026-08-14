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
