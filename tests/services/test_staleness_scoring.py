from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.staleness_scoring import compute_staleness_score

class _FakeDoc:
    def __init__(self, id=1, last_reviewed_at=None):
        self.id = id
        self.last_reviewed_at = last_reviewed_at

def test_compute_staleness_score_no_db_no_review():
    doc = _FakeDoc(id=1, last_reviewed_at=None)
    score = compute_staleness_score(None, doc)
    assert score == 100.0

def test_compute_staleness_score_no_db_recent_review():
    doc = _FakeDoc(id=1, last_reviewed_at=datetime.now(timezone.utc) - timedelta(days=5))
    score = compute_staleness_score(None, doc)
    assert score == 10.0

@patch("app.services.staleness_scoring.usage_analytics.get_popular_documents")
@patch("app.services.staleness_scoring.feedback_service.get_top_negative_feedback_queries")
def test_compute_staleness_score_with_db(mock_get_neg, mock_get_popular):
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
