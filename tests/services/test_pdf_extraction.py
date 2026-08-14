import fitz
import pytest
from app.services.pdf_extraction import extract_pdf_pages

def _create_sample_pdf_bytes(text: str = "Hello from test PDF page") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes

def test_extract_pdf_pages_valid():
    pdf_bytes = _create_sample_pdf_bytes("Page 1 text content")
    pages = extract_pdf_pages(pdf_bytes)
    assert len(pages) == 1
    assert pages[0]["page_number"] == 1
    assert "Page 1 text content" in pages[0]["text"]

def test_extract_pdf_pages_empty_pages_ignored():
    doc = fitz.open()
    doc.new_page()  # empty page
    pdf_bytes = doc.write()
    doc.close()

    pages = extract_pdf_pages(pdf_bytes)
    assert pages == []
