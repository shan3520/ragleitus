from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.evaluation import Base
from app.models.document import Document, SearchQueryLog, DocumentRetrievalLog
from app.models.feedback import SearchFeedback
from app.services.feedback_service import calculate_document_negative_impact, create_feedback


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


def test_negative_impact_counts_full_history_without_limits_or_windows(session):
    doc = Document(user_id=1, title="Long History Doc")
    session.add(doc)
    session.flush()
    other_docs = [Document(user_id=1, title=f"Other Doc {i}") for i in range(3)]
    session.add_all(other_docs)
    session.flush()

    old_timestamp = datetime.now(timezone.utc) - timedelta(days=90)

    def _bulk_add_negative_feedback(feedback_count, documents, created_at):
        query_logs = [
            SearchQueryLog(query_text=f"bulk negative query {created_at} {i}")
            for i in range(feedback_count)
        ]
        session.add_all(query_logs)
        session.flush()
        session.add_all(
            SearchFeedback(
                search_log_id=q.id,
                is_positive=False,
                created_at=created_at,
                documents=list(documents),
            )
            for q in query_logs
        )
        session.flush()

    _bulk_add_negative_feedback(1300, [doc], old_timestamp)
    _bulk_add_negative_feedback(1600, other_docs, datetime.now(timezone.utc))
    session.commit()

    score = calculate_document_negative_impact(session, doc.id)

    assert score == 1300.0


def _create_query_with_retrieval(session, doc):
    query_log = SearchQueryLog(query_text=f"query for {doc.title}")
    session.add(query_log)
    session.flush()
    retrieval = DocumentRetrievalLog(query_log_id=query_log.id, document_id=doc.id)
    session.add(retrieval)
    session.commit()
    return query_log.id


def test_does_not_flag_document_below_threshold(session):
    doc = Document(user_id=1, title="Below Threshold Doc")
    session.add(doc)
    session.commit()

    qid1 = _create_query_with_retrieval(session, doc)
    qid2 = _create_query_with_retrieval(session, doc)

    create_feedback(session, qid1, is_positive=False)
    create_feedback(session, qid2, is_positive=False)

    session.refresh(doc)
    assert doc.review_status is None


def test_flags_document_when_negative_feedback_reaches_threshold(session):
    doc = Document(user_id=1, title="At Threshold Doc")
    session.add(doc)
    session.commit()

    qid1 = _create_query_with_retrieval(session, doc)
    qid2 = _create_query_with_retrieval(session, doc)
    qid3 = _create_query_with_retrieval(session, doc)

    create_feedback(session, qid1, is_positive=False)
    create_feedback(session, qid2, is_positive=False)

    session.refresh(doc)
    assert doc.review_status is None

    create_feedback(session, qid3, is_positive=False)

    session.refresh(doc)
    assert doc.review_status == "needs_review"


def test_feedback_on_a_missing_or_foreign_search_log_is_refused(session):
    from app.services.feedback_service import SearchLogNotFoundError

    with pytest.raises(SearchLogNotFoundError):
        create_feedback(session, search_log_id=999, is_positive=True, user_id=1)

    log = SearchQueryLog(query_text="whose query?", user_id=2)
    session.add(log)
    session.commit()
    with pytest.raises(SearchLogNotFoundError):
        create_feedback(session, search_log_id=log.id, is_positive=False, user_id=1)
    assert create_feedback(session, search_log_id=log.id, is_positive=True, user_id=2).search_log_id == log.id
