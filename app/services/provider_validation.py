import re
from typing import Optional
from urllib import error, request


KEY_PATTERNS = {
    "openai": re.compile(r"^sk-[A-Za-z0-9]{8,}$"),
    "gemini": re.compile(r"^AIza[0-9A-Za-z\-_]{20,}$"),
}


def is_valid_provider_key_format(provider: str, key: str) -> bool:
    pattern = KEY_PATTERNS.get(provider.lower())
    return bool(pattern and pattern.match(key))


def verify_provider_key(provider: str, key: str, client: Optional[object] = None) -> bool:
    if not is_valid_provider_key_format(provider, key):
        return False

    if client is None:
        return True

    url = f"https://example.invalid/{provider}/verify"
    req = request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        resp = client.post(req, json={"key": key})
        return getattr(resp, "status_code", 500) == 200
    except error.URLError:
        return False
