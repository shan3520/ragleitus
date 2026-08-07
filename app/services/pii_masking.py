'''PII masking service.'''
import re
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

def mask_pii(text: str) -> str:
    if not text:
        return ""
    return EMAIL_RE.sub("[REDACTED_EMAIL]", text)
