"""The API image must start uvicorn without its own proxy-header handling.

Uvicorn's --proxy-headers (on by default) replaces the client address with
X-Forwarded-For for connections from 127.0.0.1 before the app sees the
request, which would let a caller pick its own rate-limit key. The app checks
X-Forwarded-For itself against TRUSTED_PROXIES (app/core/client_identity.py).
"""

import json
import re
from pathlib import Path


def test_api_image_disables_uvicorn_proxy_headers():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    cmd = json.loads(re.search(r"^CMD (\[.*\])$", dockerfile, re.MULTILINE).group(1))
    assert cmd[0] == "uvicorn"
    assert "--no-proxy-headers" in cmd
