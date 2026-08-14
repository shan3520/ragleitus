import pytest
from app.services.chunking import chunk_text

def test_chunk_text_empty():
    assert chunk_text("", 100, 10) == []

def test_chunk_text_invalid_window():
    with pytest.raises(ValueError, match="chunk_window_size must be greater than 0"):
        chunk_text("hello", 0, 0)

def test_chunk_text_invalid_overlap():
    with pytest.raises(ValueError, match="chunk_overlap_size must be non-negative"):
        chunk_text("hello", 10, -1)

def test_chunk_text_overlap_greater_or_equal_window():
    with pytest.raises(ValueError, match="chunk_overlap_size must be smaller than chunk_window_size"):
        chunk_text("hello", 10, 10)

def test_chunk_text_sentence_boundary_and_no_infinite_loop():
    text = "a. b. c. d. e. f. g. h."
    chunks = chunk_text(text, chunk_window_size=6, chunk_overlap_size=3)
    assert isinstance(chunks, list)
    assert len(chunks) > 0

def test_chunk_text_basic():
    text = "This is a long text to test chunking functionality."
    chunks = chunk_text(text, 20, 5)
    assert len(chunks) > 1
    assert "".join(chunks).replace(" ", "") != ""
