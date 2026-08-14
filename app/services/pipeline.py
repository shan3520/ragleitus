"""
End-to-end RAG document ingestion pipeline service.

Orchestrates text extraction (PDF / raw text), page cleaning,
and sentence-aware sliding window chunking.
"""

import hashlib
from typing import Optional

from app.services.pdf_extraction import extract_pdf_pages
from app.services.text_cleaning import clean_text_pages
from app.services.chunking import chunk_text as chunk_text_service


def extract_text(content_bytes: bytes) -> str:
    """Extract text from PDF content bytes."""
    pages = extract_pdf_pages(content_bytes)
    return "\n\n".join(page["text"] for page in pages if page.get("text"))


def clean_text(text: str) -> str:
    """Clean extracted text using page-level cleaning."""
    if not text:
        return ""
    cleaned_pages = clean_text_pages([text])
    return cleaned_pages[0] if cleaned_pages else ""


def chunk_text(text: str, window_size: int = 800, overlap_size: int = 100) -> list[str]:
    """Split cleaned text into sliding window chunks."""
    return chunk_text_service(text, window_size, overlap_size)


def process_document_pipeline(
    content_bytes: bytes,
    filename: str,
    window_size: int = 800,
    overlap_size: int = 100,
) -> dict:
    """
    Run end-to-end ingestion pipeline on document bytes.

    Returns dict containing filename, sha256 hash, raw text, cleaned text, and chunks.
    """
    sha256 = hashlib.sha256(content_bytes).hexdigest()

    if filename.lower().endswith(".pdf"):
        extracted_pages = extract_pdf_pages(content_bytes)
        raw_page_texts = [p["text"] for p in extracted_pages if p.get("text")]
        cleaned_pages = clean_text_pages(raw_page_texts) if raw_page_texts else []
        full_cleaned_text = "\n\n".join(cleaned_pages)
    else:
        raw_text = content_bytes.decode("utf-8", errors="ignore")
        full_cleaned_text = clean_text(raw_text)

    chunks = chunk_text_service(full_cleaned_text, window_size, overlap_size)

    return {
        "filename": filename,
        "sha256": sha256,
        "content": full_cleaned_text,
        "chunks": chunks,
    }
