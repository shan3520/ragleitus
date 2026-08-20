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
