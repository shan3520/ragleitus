import re
from collections import Counter


_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _normalize_text(text: str) -> str:
    text = _CONTROL_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def clean_text_pages(pages: list[str]) -> list[str]:
    lines_per_page = []
    for page in pages:
        page = _CONTROL_RE.sub("", page)
        lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in page.splitlines()]
        lines_per_page.append([line for line in lines if line])

    line_counts = Counter()
    for lines in lines_per_page:
        seen = set()
        for line in lines:
            stripped = line.strip()
            if stripped:
                seen.add(stripped)
        line_counts.update(seen)

    repeated = {
        line
        for line, count in line_counts.items()
        if count > 1 and len(line) <= 120
    }

    result = []
    for page in lines_per_page:
        filtered = [line for line in page if line.strip() not in repeated]
        result.append(_normalize_text("\n".join(filtered)))
    return result
