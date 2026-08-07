'''Document metadata and tag extraction service.'''
def extract_metadata(title: str, text: str) -> dict:
    return {
        "title": title or "Untitled",
        "char_count": len(text or ""),
        "word_count": len((text or "").split()),
        "has_code": "def " in (text or "") or "function" in (text or ""),
    }
