from app.services.pipeline import extract_text, clean_text, chunk_text, process_document_pipeline

def test_pipeline_text_cleaning_and_chunking():
    dirty_text = "\x00Hello world! \n\nThis is a sample document for RAG ingestion."
    cleaned = clean_text(dirty_text)
    assert "\x00" not in cleaned
    assert "Hello world!" in cleaned

    chunks = chunk_text(cleaned, window_size=50, overlap_size=10)
    assert isinstance(chunks, list)
    assert len(chunks) > 0

def test_process_document_pipeline_text_file():
    content = b"Sample raw document text for ingestion."
    result = process_document_pipeline(content, "sample.txt", window_size=30, overlap_size=5)

    assert result["filename"] == "sample.txt"
    assert "sha256" in result
    assert result["content"] == "Sample raw document text for ingestion."
    assert isinstance(result["chunks"], list)
