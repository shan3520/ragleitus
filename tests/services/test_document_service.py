import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.evaluation import Base
from app.models.document import Document, SearchQueryLog
from app.models.feedback import SearchFeedback
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
        user_id=1,
        title="Test PDF Document",
        content="Full text content",
        chunk_contents=["Chunk 1 content", "Chunk 2 content"],
        sha256="abc123hash",
    )
    session.commit()

    assert doc.id is not None
    assert doc.user_id == 1
    assert doc.title == "Test PDF Document"
    assert len(doc.chunks) == 2
    assert doc.chunks[0].sequence_order == 1

    # List documents
    user1_docs = list_user_documents(session, 1)
    assert len(user1_docs) == 1
    assert user1_docs[0].id == doc.id

    user2_docs = list_user_documents(session, 2)
    assert len(user2_docs) == 0

    # Get document
    retrieved = get_user_document(session, doc.id, 1)
    assert retrieved is not None
    assert retrieved.id == doc.id

    non_retrieved = get_user_document(session, doc.id, 2)
    assert non_retrieved is None

    # Delete document
    deleted = delete_user_document(session, doc.id, 1)
    session.commit()
    assert deleted is True

    assert get_user_document(session, doc.id, 1) is None
    assert delete_user_document(session, doc.id, 1) is False


from unittest.mock import patch

def _add_feedback(session, document, is_positive):
    log = SearchQueryLog(query_text=f"query-{document.id}-{is_positive}")
    session.add(log)
    session.flush()
    feedback = SearchFeedback(search_log_id=log.id, is_positive=is_positive)
    feedback.documents.append(document)
    session.add(feedback)
    return feedback


def test_list_user_documents_aggregates_negative_impact_without_cross_contamination():
    session = _setup_in_memory_db()

    doc_none = create_document_with_chunks(
        session=session, user_id=3, title="NoFeedbackDoc",
        content="Full text content", chunk_contents=["a", "b"],
    )
    doc_one = create_document_with_chunks(
        session=session, user_id=3, title="OneNegativeDoc",
        content="Full text content", chunk_contents=["a"],
    )
    doc_three = create_document_with_chunks(
        session=session, user_id=3, title="ThreeNegativesDoc",
        content="Full text content", chunk_contents=["a", "b", "c"],
    )
    other_user_doc = create_document_with_chunks(
        session=session, user_id=4, title="OtherUserDoc",
        content="Full text content", chunk_contents=["a"],
    )
    session.flush()

    _add_feedback(session, doc_one, False)
    _add_feedback(session, doc_one, True)
    _add_feedback(session, doc_one, True)
    for _ in range(3):
        _add_feedback(session, doc_three, False)
        _add_feedback(session, other_user_doc, False)

    session.commit()

    result = list_user_documents(session, 3)

    assert isinstance(result, list)
    assert len(result) == 3
    assert all(isinstance(doc, Document) for doc in result)

    by_id = {doc.id: doc for doc in result}
    assert set(by_id) == {doc_none.id, doc_one.id, doc_three.id}

    assert by_id[doc_none.id].negative_impact == 0.0
    assert isinstance(by_id[doc_none.id].negative_impact, float)
    assert by_id[doc_one.id].negative_impact == 1.0
    assert by_id[doc_three.id].negative_impact == 3.0


def test_list_user_documents_issues_a_single_query():
    session = _setup_in_memory_db()

    doc_a = create_document_with_chunks(
        session=session, user_id=5, title="DocA",
        content="Full text content", chunk_contents=["a", "b"],
    )
    doc_b = create_document_with_chunks(
        session=session, user_id=5, title="DocB",
        content="Full text content", chunk_contents=["a"],
    )
    session.flush()
    for _ in range(2):
        _add_feedback(session, doc_a, False)
    _add_feedback(session, doc_b, True)

    session.commit()

    statements = []

    def _record_select(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _record_select)
    try:
        result = list_user_documents(session, 5)
    finally:
        event.remove(engine, "before_cursor_execute", _record_select)

    assert len(result) == 2
    assert len(statements) == 1

@patch("app.services.document_service.invalidate_staleness_cache")
def test_mark_document_reviewed(mock_invalidate):
    from app.services.document_service import mark_document_reviewed
    session = _setup_in_memory_db()

    doc = create_document_with_chunks(
        session=session,
        user_id=6,
        title="Review Document",
        content="Full text content",
        chunk_contents=[],
        sha256="abc123hash",
    )
    session.commit()


    # Initial state
    assert doc.last_reviewed_at is None

    # Mark as reviewed
    reviewed_doc = mark_document_reviewed(session, 6, doc.id)
    assert reviewed_doc is not None
    assert reviewed_doc.id == doc.id
    assert reviewed_doc.last_reviewed_at is not None
    mock_invalidate.assert_called_once()

    # Try with wrong user
    mock_invalidate.reset_mock()
    non_doc = mark_document_reviewed(session, 7, doc.id)
    assert non_doc is None
    mock_invalidate.assert_not_called()
