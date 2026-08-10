"""Payload string sanitization utility."""
import re

def sanitize_string(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return cleaned.strip()
