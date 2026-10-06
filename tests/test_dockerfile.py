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


def test_the_evaluator_extras_can_be_left_out_of_the_image():
    """The image installs the extras named by EXTRAS (default: both evaluators),
    and docker-compose.yml passes EVALUATOR_EXTRAS to the api and the worker alike."""
    import tomllib

    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    default = re.search(r'^ARG EXTRAS="([^"]*)"$', dockerfile, re.MULTILINE).group(1)
    assert default == "ragas,deepeval"
    # An empty EXTRAS installs the package without extras ("." rather than ".[]").
    assert 'pip install ".${EXTRAS:+[$EXTRAS]}"' in dockerfile
    extras = tomllib.loads((root / "pyproject.toml").read_text())["project"]["optional-dependencies"]
    assert set(default.split(",")) <= set(extras)

    compose = (root / "docker-compose.yml").read_text()
    assert "EXTRAS: ${EVALUATOR_EXTRAS-ragas,deepeval}" in compose
    assert re.search(r"^  api:\n    build: &backend-build$", compose, re.MULTILINE)
    assert re.search(r"^  worker:\n    build: \*backend-build$", compose, re.MULTILINE)


def test_the_extras_expansion_installs_what_it_should():
    """The shell expansion in the Dockerfile, run for real."""
    import subprocess

    def pip_target(extras: str) -> str:
        return subprocess.run(
            ["sh", "-c", 'echo ".${EXTRAS:+[$EXTRAS]}"'], env={"EXTRAS": extras}, capture_output=True, text=True, check=True,
        ).stdout.strip()

    assert pip_target("ragas,deepeval") == ".[ragas,deepeval]"
    assert pip_target("ragas") == ".[ragas]"
    assert pip_target("") == "."
