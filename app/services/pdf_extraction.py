import fitz


def extract_pdf_pages(pdf_bytes: bytes) -> list[dict]:
    pages: list[dict] = []
    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for index, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append({"page_number": index, "text": text})
    finally:
        pdf.close()
    return pages
