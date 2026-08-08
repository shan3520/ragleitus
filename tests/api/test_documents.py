import fitz
from fastapi.testclient import TestClient

from app.main import app


def test_document_pdf_extract_endpoint():
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Page 1 text")
    pdf.new_page()
    page = pdf.new_page()
    page.insert_text((72, 72), "Page 3 text")
    pdf_bytes = pdf.tobytes()
    pdf.close()

    client = TestClient(app)
    response = client.post(
       "/documents/extract",
       files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pages"] == [
       {"page_number": 1, "text": "Page 1 text"},
       {"page_number": 3, "text": "Page 3 text"},
    ]
