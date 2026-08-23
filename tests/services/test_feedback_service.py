import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.evaluation import Base
from app.models.document import Document, SearchQueryLog
from app.models.feedback import SearchFeedback
from app.services.feedback_service import calculate_document_negative_impact


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


def _add_negative_feedback(session, document):
    query_log = SearchQueryLog(query_text=f"negative query for {document.title}")
    session.add(query_log)
    session.flush()
    feedback = SearchFeedback(
        search_log_id=query_log.id,
        is_positive=False,
        documents=[document],
    )
    session.add(feedback)
    session.flush()


def test_document_with_no_feedback_returns_zero(session):
    doc = Document(user_id=1, title="No Feedback Doc")
    session.add(doc)
    session.commit()

    score = calculate_document_negative_impact(session, doc.id)

    assert score == 0.0
    assert isinstance(score, float)


def test_counts_only_negative_feedback_as_impact(session):
    doc = Document(user_id=1, title="Mixed Feedback Doc")
    session.add(doc)
    session.flush()

    for _ in range(3):
        _add_negative_feedback(session, doc)

    query_log = SearchQueryLog(query_text="positive query")
    session.add(query_log)
    session.flush()
    positive_feedback = SearchFeedback(
        search_log_id=query_log.id,
        is_positive=True,
        documents=[doc],
    )
    session.add(positive_feedback)
    session.commit()

    score = calculate_document_negative_impact(session, doc.id)

    assert score == 3.0
