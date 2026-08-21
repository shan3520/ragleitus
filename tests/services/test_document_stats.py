"""Tests for app.services.document_stats."""

from app.services.document_stats import compute_document_stats, DocumentStats


class _FakeDoc:
    """Minimal stand-in for a Document model instance."""

    def __init__(self, status="pending", content="", num_chunks=0):
        self.status = status
        self.content = content
        self.chunks = [object() for _ in range(num_chunks)]


def test_empty_collection():
    result = compute_document_stats([])
    assert result == DocumentStats(
        total_documents=0,
        total_chunks=0,
        avg_chunks_per_document=0.0,
        status_counts={},
        total_content_length=0,
    )


def test_single_document_no_chunks():
    doc = _FakeDoc(status="indexed", content="Hello world", num_chunks=0)
    result = compute_document_stats([doc])
    assert result.total_documents == 1
    assert result.total_chunks == 0
    assert result.avg_chunks_per_document == 0.0
    assert result.status_counts == {"indexed": 1}
    assert result.total_content_length == len("Hello world")


def test_multiple_documents_mixed_status():
    docs = [
        _FakeDoc(status="pending", content="abc", num_chunks=2),
        _FakeDoc(status="indexed", content="defgh", num_chunks=5),
        _FakeDoc(status="pending", content="ij", num_chunks=3),
    ]
    result = compute_document_stats(docs)
    assert result.total_documents == 3
    assert result.total_chunks == 10
    assert result.avg_chunks_per_document == round(10 / 3, 2)
    assert result.status_counts == {"pending": 2, "indexed": 1}
    assert result.total_content_length == 10  # 3 + 5 + 2


def test_custom_accessors():
    """Verify that custom accessor callables work."""
    data = [{"s": "done", "c": "text", "ch": [1, 2]}]
    result = compute_document_stats(
        data,
        get_chunks=lambda d: d["ch"],
        get_status=lambda d: d["s"],
        get_content=lambda d: d["c"],
    )
    assert result.total_documents == 1
    assert result.total_chunks == 2
    assert result.status_counts == {"done": 1}
    assert result.total_content_length == 4


def test_none_content_treated_as_empty():
    """Documents with ``None`` content should contribute 0 length."""
    doc = _FakeDoc(status="error", content=None, num_chunks=0)
    # The default get_content accessor does ``or ""`` for None
    result = compute_document_stats([doc])
    assert result.total_content_length == 0

from unittest.mock import patch

@patch("app.services.document_stats.compute_staleness_score")
def test_compute_document_stats_with_staleness(mock_score):
    mock_score.side_effect = [10.0, 50.0]
    docs = [
        _FakeDoc(status="indexed", content="abc", num_chunks=1),
        _FakeDoc(status="indexed", content="def", num_chunks=1),
    ]
    
    result = compute_document_stats(docs, db="fake_db")
    
    assert mock_score.call_count == 2
    assert result.total_documents == 2
    assert result.max_staleness_score == 50.0
    assert result.avg_staleness_score == 30.0

@patch("app.services.document_stats.calculate_document_disappointment_ratio")
@patch("app.services.document_stats.compute_staleness_score")
def test_compute_document_stats_with_disappointment(mock_staleness, mock_ratio):
    mock_staleness.return_value = 0.0
    mock_ratio.side_effect = [0.1, 0.5]
    docs = [
        _FakeDoc(status="indexed", content="abc", num_chunks=1),
        _FakeDoc(status="indexed", content="def", num_chunks=1),
    ]
    
    result = compute_document_stats(docs, db="fake_db")
    
    assert mock_ratio.call_count == 2
    assert result.max_disappointment_ratio == 0.5
    assert result.avg_disappointment_ratio == 0.3

def test_calculate_document_disappointment_ratio_division_by_zero():
    from app.services.document_stats import calculate_document_disappointment_ratio
    from unittest.mock import Mock
    
    mock_db = Mock()
    # Mocking a chain of calls like db.query().join().filter().scalar()
    # We want retrievals scalar to return 0
    mock_db.query.return_value.join.return_value.filter.return_value.scalar.side_effect = [5, 0] 
    
    ratio = calculate_document_disappointment_ratio(mock_db, 1)
    assert ratio == 0.0

def test_calculate_document_disappointment_ratio_valid():
    from app.services.document_stats import calculate_document_disappointment_ratio
    from unittest.mock import Mock
    
    mock_db = Mock()
    mock_db.query.return_value.join.return_value.filter.return_value.scalar.side_effect = [1, 4] 
    
    ratio = calculate_document_disappointment_ratio(mock_db, 1)
    assert ratio == 0.25


from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import NoSearchActivityError
from app.models import Base
from app.models.document import Document, DocumentRetrievalLog, SearchQueryLog
from app.services.document_stats import get_unsearched_documents, get_underperforming_document_ids


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _add_search_log(session, query_text, timestamp):
    log = SearchQueryLog(query_text=query_text, timestamp=timestamp)
    session.add(log)
    session.commit()
    return log


def test_no_search_activity_raises_error(db_session):
    """With zero SearchQueryLog entries since the cutoff, the service must
    raise NoSearchActivityError instead of returning a (meaningless) list."""
    # Case 1: no search logs at all.
    with pytest.raises(NoSearchActivityError):
        get_unsearched_documents(db_session, days=30)

    # Case 2: a search log exists, but it predates the cutoff, so there is
    # still no activity within the window.
    stale_timestamp = datetime.utcnow() - timedelta(days=60)
    _add_search_log(db_session, "stale query", stale_timestamp)
    with pytest.raises(NoSearchActivityError):
        get_unsearched_documents(db_session, days=30)


def test_document_created_after_cutoff_is_excluded(db_session):
    """A document created after the cutoff date must never appear in the
    unsearched documents list, even though it has no retrievals."""
    now = datetime.utcnow()
    recent_doc = Document(
        title="Recent doc", status="ready", created_at=now - timedelta(days=1)
    )
    old_doc = Document(
        title="Old doc", status="ready", created_at=now - timedelta(days=60)
    )
    db_session.add_all([recent_doc, old_doc])
    _add_search_log(db_session, "recent query", now)

    result = get_unsearched_documents(db_session, days=30)

    result_ids = [doc.id for doc in result]
    assert old_doc.id in result_ids
    assert recent_doc.id not in result_ids


def test_document_retrieved_after_cutoff_is_excluded(db_session):
    """A document retrieved in a search after the cutoff must not appear in
    the unsearched documents list."""
    now = datetime.utcnow()
    long_ago = now - timedelta(days=60)
    retrieved_doc = Document(
        title="Recently retrieved", status="ready", created_at=long_ago
    )
    untouched_doc = Document(
        title="Never retrieved", status="ready", created_at=long_ago
    )
    db_session.add_all([retrieved_doc, untouched_doc])
    db_session.commit()

    log = _add_search_log(db_session, "recent query", now)
    db_session.add(
        DocumentRetrievalLog(query_log_id=log.id, document_id=retrieved_doc.id)
    )
    db_session.commit()

    result = get_unsearched_documents(db_session, days=30)

    result_ids = [doc.id for doc in result]
    assert untouched_doc.id in result_ids
    assert retrieved_doc.id not in result_ids


def test_documents_straddling_n_day_cutoff_only_older_returned(db_session):
    """A document created slightly newer than the N-day cutoff is still
    inside its fair chance window; only the older one may be unsearched."""
    now = datetime.utcnow()
    newer_doc = Document(
        title="Just uploaded", status="ready", created_at=now - timedelta(days=29)
    )
    older_doc = Document(
        title="Settled doc", status="ready", created_at=now - timedelta(days=31)
    )
    db_session.add_all([newer_doc, older_doc])
    _add_search_log(db_session, "activity query", now)

    result = get_unsearched_documents(db_session, days=30)

    result_ids = [doc.id for doc in result]
    assert result_ids == [older_doc.id]
    assert newer_doc.id not in result_ids


def test_retrieval_exactly_on_oldest_day_of_window_excludes_document(db_session):
    """A document retrieved exactly on the oldest day of the analysis window
    counts as searched (the window is inclusive), so it must not be listed."""
    frozen_now = datetime.utcnow()

    class _FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return frozen_now

    doc = Document(
        title="Boundary doc", status="ready", created_at=frozen_now - timedelta(days=60)
    )
    db_session.add(doc)
    db_session.commit()

    boundary_log = _add_search_log(
        db_session, "boundary query", frozen_now - timedelta(days=30)
    )
    _add_search_log(db_session, "inner query", frozen_now - timedelta(days=1))
    db_session.add(
        DocumentRetrievalLog(query_log_id=boundary_log.id, document_id=doc.id)
    )
    db_session.commit()

    with patch("app.services.document_stats.datetime", _FrozenDatetime):
        result = get_unsearched_documents(db_session, days=30)

    assert [d.id for d in result] == []


def test_window_with_zero_search_logs_raises_error(db_session):
    """A requested window containing zero SearchQueryLog rows must raise
    NoSearchActivityError even when other windows do have activity."""
    _add_search_log(db_session, "old query", datetime.utcnow() - timedelta(days=90))

    with pytest.raises(NoSearchActivityError):
        get_unsearched_documents(db_session, days=7)


def _add_document(session, title):
    doc = Document(title=title, status="ready")
    session.add(doc)
    session.commit()
    return doc


def _add_retrievals(session, log, doc, count):
    session.add_all(
        DocumentRetrievalLog(query_log_id=log.id, document_id=doc.id)
        for _ in range(count)
    )
    session.commit()


def test_underperforming_ids_exclude_zero_return_documents(db_session):
    """A document with zero search returns must never be reported as an
    underperforming candidate, even when a sibling document qualifies."""
    now = datetime.utcnow()
    shown = _add_document(db_session, "shown doc")
    never_shown = _add_document(db_session, "never shown doc")

    log = _add_search_log(db_session, "window query", now)
    _add_retrievals(db_session, log, shown, 5)

    result = get_underperforming_document_ids(
        db_session, [shown.id, never_shown.id], days=30
    )

    assert shown.id in result
    assert never_shown.id not in result


def test_underperforming_ids_respect_min_shown_threshold(db_session):
    """When ``min_shown`` is provided, documents whose retrieval count is
    below it must be excluded even though they clear the default floor."""
    now = datetime.utcnow()
    low = _add_document(db_session, "low traffic doc")
    high = _add_document(db_session, "high traffic doc")

    log = _add_search_log(db_session, "traffic query", now)
    _add_retrievals(db_session, log, low, 6)
    _add_retrievals(db_session, log, high, 9)

    result = get_underperforming_document_ids(
        db_session, [low.id, high.id], days=30, min_shown=8
    )

    assert high.id in result
    assert low.id not in result

    # Without min_shown the low-traffic document still clears the default
    # min_retrievals floor, proving the parameter actually narrows results.
    baseline = get_underperforming_document_ids(
        db_session, [low.id, high.id], days=30
    )
    assert baseline == {low.id, high.id}
