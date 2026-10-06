"""Live tests: RAGForge's provider adapters against the real services.

They cost a little money and need keys, so they never run by default:
`pytest` deselects them (pyproject.toml), and each provider's tests are
skipped unless its key is set. Run them with

    OPENAI_API_KEY=... ANTHROPIC_API_KEY=... pytest -m live tests/live -v

Keys are read from these environment variables (RAGFORGE itself never
reads them; users store keys through the app):

    OPENAI_API_KEY  ANTHROPIC_API_KEY  GEMINI_API_KEY  GROQ_API_KEY
    OPENROUTER_API_KEY  NVIDIA_API_KEY  TOGETHER_API_KEY  MISTRAL_API_KEY

A self-hosted OpenAI-compatible server (Ollama, vLLM, LM Studio) is tested
with LIVE_CUSTOM_BASE_URL (e.g. http://localhost:11434/v1), LIVE_CUSTOM_MODEL
and optionally LIVE_CUSTOM_API_KEY, LIVE_CUSTOM_EMBEDDING_MODEL and
LIVE_CUSTOM_RERANK_MODEL.

The models default to each provider's defaults in the app; override them
with LIVE_<PROVIDER>_MODEL, LIVE_<PROVIDER>_EMBEDDING_MODEL and
LIVE_<PROVIDER>_RERANK_MODEL (e.g. LIVE_ANTHROPIC_MODEL=claude-haiku-4-5).
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from tests import network
from tests.live.providers import KEY_VARIABLES, Live, live_provider


@pytest.fixture(autouse=True)
def _real_network(monkeypatch):
    network.allow(monkeypatch)
    # A self-hosted server is usually on this machine or the LAN.
    monkeypatch.setattr(settings, "allow_private_provider_urls", True)


@pytest.fixture(params=list(KEY_VARIABLES))
def live(request) -> Live:
    configured = live_provider(request.param)
    if configured is None:
        variable = "LIVE_CUSTOM_BASE_URL" if request.param == "custom" else KEY_VARIABLES[request.param]
        pytest.skip(f"{variable} is not set")
    if not configured.model:
        pytest.skip(f"LIVE_{request.param.upper()}_MODEL is not set")
    return configured
