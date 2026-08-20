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
