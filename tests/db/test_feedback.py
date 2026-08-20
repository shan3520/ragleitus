import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.evaluation import Base
from app.models.document import SearchQueryLog
from app.models.feedback import SearchFeedback

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()

def test_insert_search_feedback(session):
    # Insert a dummy search query log first to satisfy foreign key constraints
    query_log = SearchQueryLog(query_text="what is rag")
    session.add(query_log)
    session.commit()

    # Insert a feedback record
    feedback = SearchFeedback(
        search_log_id=query_log.id,
        is_positive=True,
        comment="Great search result!"
    )
    session.add(feedback)
    session.commit()

    # Verify the schema integrity and insertion
    db_feedback = session.query(SearchFeedback).filter_by(search_log_id=query_log.id).first()
    assert db_feedback is not None
    assert db_feedback.is_positive is True
    assert db_feedback.comment == "Great search result!"
    assert db_feedback.created_at is not None
    assert db_feedback.search_log.query_text == "what is rag"

def test_document_feedback_relationship_and_cascade(session):
    from app.models.document import Document
    from app.models.feedback import document_feedback

    query_log = SearchQueryLog(query_text="cascade test")
    session.add(query_log)
    
    doc = Document(title="Cascade Doc", status="ready")
    session.add(doc)
    
    feedback = SearchFeedback(
        search_log=query_log,
        is_positive=True,
        comment="Needs cascade",
        documents=[doc]
    )
    session.add(feedback)
    session.commit()

    # Verify relationship works both ways
    assert len(doc.feedbacks) == 1
    assert doc.feedbacks[0].comment == "Needs cascade"
    assert len(feedback.documents) == 1
    assert feedback.documents[0].title == "Cascade Doc"

    doc_id = doc.id
    feedback_id = feedback.id

    # Verify the link exists
    res = session.execute(document_feedback.select().where(document_feedback.c.document_id == doc_id)).fetchall()
    assert len(res) == 1

    # Now verify cascade behavior: removing a Document removes the link
    session.delete(doc)
    session.commit()

    # Verify the link is removed
    res = session.execute(document_feedback.select().where(document_feedback.c.document_id == doc_id)).fetchall()
    assert len(res) == 0
