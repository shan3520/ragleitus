"""Tests for app.services.document_search."""

from app.services.document_search import generate_snippet, search_documents


class _FakeDoc:
    """Minimal stand-in for a Document model instance."""

    def __init__(self, doc_id: int, title: str, content: str):
        self.id = doc_id
        self.title = title
        self.content = content


def test_search_documents_empty_query():
    docs = [_FakeDoc(1, "Test", "Content")]
    assert search_documents(docs, "") == []
    assert search_documents(docs, "   ") == []


def test_search_documents_title_and_content_match():
    docs = [
        _FakeDoc(1, "Python RAG", "Building Python retrieval augmented generation"),
        _FakeDoc(2, "FastAPI guide", "FastAPI web framework with Python"),
        _FakeDoc(3, "Database", "SQLAlchemy ORM setup"),
    ]

    matches = search_documents(docs, "Python")
    assert len(matches) == 2
    # doc 1 matches both title and content -> score 3.0
    assert matches[0].document_id == 1
    assert matches[0].score == 3.0
    # doc 2 matches content only -> score 1.0
    assert matches[1].document_id == 2
    assert matches[1].score == 1.0


def test_search_documents_no_match():
    docs = [_FakeDoc(1, "Title", "Content")]
    assert search_documents(docs, "nonexistent") == []


def test_generate_snippet_centered():
    text = "The quick brown fox jumps over the lazy dog near the river bank."
    snippet = generate_snippet(text, "fox", max_length=20)
    assert "fox" in snippet


def test_generate_snippet_empty_inputs():
    assert generate_snippet("", "query") == ""
    assert generate_snippet("text", "") == "text"
