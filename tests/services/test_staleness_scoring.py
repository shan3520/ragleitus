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

@patch("app.services.staleness_scoring.usage_analytics.get_popular_documents")
@patch("app.services.staleness_scoring.feedback_service.get_top_negative_feedback_queries")
def test_compute_staleness_score_with_db(mock_get_neg, mock_get_popular):
    invalidate_staleness_cache()
    db_mock = MagicMock()
    doc = _FakeDoc(id=1, last_reviewed_at=None)
    
    mock_get_popular.return_value = [{"document_id": 1, "count": 3}]
    mock_get_neg.return_value = [{"query_text": "bad info", "count": 2}]
    
    query_mock = db_mock.query.return_value
    join_mock = query_mock.join.return_value
    filter_mock = join_mock.filter.return_value
    filter_mock.count.return_value = 2
    
    score = compute_staleness_score(db_mock, doc)
    
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
