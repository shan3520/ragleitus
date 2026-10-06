"""Payload string sanitization utility."""
import re

def sanitize_string(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return cleaned.strip()


def spreadsheet_safe(value):
    """A CSV cell that spreadsheet apps will not run as a formula.

    Cells starting with =, +, -, @, tab or carriage return are formulas to
    Excel, LibreOffice and Google Sheets; a leading apostrophe keeps them text.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value
