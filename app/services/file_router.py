'''Multi-format document file routing service.'''
from app.services.pdf_extraction import extract_pdf_pages
from app.services.csv_extraction import parse_csv_content
from app.services.json_extraction import parse_json_content
from app.services.html_extraction import strip_html_tags

def route_and_parse_file(filename: str, content_bytes: bytes) -> str:
    fname = filename.lower()
    if fname.endswith(".pdf"):
        pages = extract_pdf_pages(content_bytes)
        return "\n".join(p["text"] for p in pages)
    elif fname.endswith(".csv"):
        rows = parse_csv_content(content_bytes.decode("utf-8", errors="ignore"))
        return str(rows)
    elif fname.endswith(".json"):
        obj = parse_json_content(content_bytes.decode("utf-8", errors="ignore"))
        return str(obj)
    elif fname.endswith(".html") or fname.endswith(".htm"):
        return strip_html_tags(content_bytes.decode("utf-8", errors="ignore"))
    return content_bytes.decode("utf-8", errors="ignore")
