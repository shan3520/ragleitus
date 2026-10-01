from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.staleness_scoring import compute_staleness_score, invalidate_staleness_cache, _staleness_cache

class _FakeDoc:
    def __init__(self, id=1, last_reviewed_at=None):
        self.id = id
        self.last_reviewed_at = last_reviewed_at

def test_compute_staleness_score_no_db_no_review():
    invalidate_staleness_cache()
    doc = _FakeDoc(id=1, last_reviewed_at=None)
    score = compute_staleness_score(None, doc)
    assert score == 100.0

def test_compute_staleness_score_no_db_recent_review():
    invalidate_staleness_cache()
    doc = _FakeDoc(id=1, last_reviewed_at=datetime.now(timezone.utc) - timedelta(days=5))
    score = compute_staleness_score(None, doc)
    assert score == 10.0

@patch("app.services.staleness_scoring.feedback_service.get_top_negative_feedback_queries")
def test_compute_staleness_score_with_db(mock_get_neg):
    invalidate_staleness_cache()
    db_mock = MagicMock()
    doc = _FakeDoc(id=1, last_reviewed_at=None)

    mock_get_neg.return_value = [{"query_text": "bad info", "count": 2}]

    # First query: usage count for this document id.
    usage_query = MagicMock()
    usage_query.filter.return_value.count.return_value = 3
    # Second query: retrievals of this document matching negative-feedback queries.
    feedback_query = MagicMock()
    feedback_query.join.return_value.filter.return_value.count.return_value = 2
    db_mock.query.side_effect = [usage_query, feedback_query]

    score = compute_staleness_score(db_mock, doc)

    assert db_mock.query.call_count == 2

    # Base: 100
    # Usage penalty: 3 * 5 = 15
    # Feedback penalty: 2 * 10 = 20
    # Total: 135.0
    assert score == 135.0

def test_staleness_caching_logic():
    invalidate_staleness_cache()
    doc = _FakeDoc(id=999, last_reviewed_at=None)
    
    # First call computes and caches
    score1 = compute_staleness_score(None, doc)
    assert score1 == 100.0
    assert _staleness_cache.get("doc_999") == 100.0
    
    # Change the doc, but should return cached
    doc.last_reviewed_at = datetime.now(timezone.utc)
    score2 = compute_staleness_score(None, doc)
    assert score2 == 100.0
    
    # Invalidate cache
    invalidate_staleness_cache()
    score3 = compute_staleness_score(None, doc)
    assert score3 == 0.0


import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.document import Document, DocumentRetrievalLog, SearchQueryLog


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _add_query_log(session, query_text, timestamp):
    log = SearchQueryLog(query_text=query_text, timestamp=timestamp)
    session.add(log)
    session.commit()
    return log


def _add_retrievals(session, query_log, document_id, count):
    session.add_all(
        DocumentRetrievalLog(query_log_id=query_log.id, document_id=document_id)
        for _ in range(count)
    )
    session.commit()


def test_staleness_score_uses_complete_history_beyond_old_top_n(db_session):
    """A document whose usage history exceeds the former global top-N slice
    (1000 records) must be scored from every record. Most of its history
    lies outside the old analytics window, so any remaining global top-N
    truncation would score it from only a subset and fail this assert."""
    invalidate_staleness_cache()
    doc = Document(user_id=1, title="history doc", status="ready", last_reviewed_at=None)
    db_session.add(doc)
    db_session.commit()

    old_log = _add_query_log(
        db_session, "old query", datetime.utcnow() - timedelta(days=40)
    )
    recent_log = _add_query_log(
        db_session, "recent query", datetime.utcnow() - timedelta(days=1)
    )
    _add_retrievals(db_session, old_log, doc.id, 1250)
    _add_retrievals(db_session, recent_log, doc.id, 300)

    score = compute_staleness_score(db_session, doc)

    # No review: 100. Complete usage history: (1250 + 300) * 5 = 7750.
    assert score == 100.0 + 1550 * 5.0
