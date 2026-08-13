'''HTML text stripping service.'''
import re

def strip_html_tags(html_text: str) -> str:
    if not html_text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", html_text)
    return " ".join(clean.split())
