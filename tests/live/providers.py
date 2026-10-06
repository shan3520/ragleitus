"""The providers the live tests can reach, from environment variables (see conftest.py)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.services.llm import create_provider, get_spec

KEY_VARIABLES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "together": "TOGETHER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "custom": "LIVE_CUSTOM_API_KEY",
}


@dataclass(frozen=True)
class Live:
    """One provider to test: its key, base URL (self-hosted only) and models."""

    name: str
    key: str
    base_url: str | None
    model: str
    embedding_model: str | None
    rerank_model: str | None

    def provider(self):
        return create_provider(self.name, self.key, self.base_url)


def _override(name: str, what: str, default: str | None) -> str | None:
    return os.environ.get(f"LIVE_{name.upper()}_{what}") or default


def live_provider(name: str) -> Live | None:
    """The provider's settings, or None when its key (or server) is not configured."""
    spec = get_spec(name)
    if name == "custom":
        base_url = os.environ.get("LIVE_CUSTOM_BASE_URL")
        if not base_url:
            return None
        key = os.environ.get("LIVE_CUSTOM_API_KEY", "")
    else:
        base_url, key = None, os.environ.get(KEY_VARIABLES[name], "")
        if not key:
            return None
    return Live(
        name=name,
        key=key,
        base_url=base_url,
        model=_override(name, "MODEL", spec.default_model) or "",
        embedding_model=_override(name, "EMBEDDING_MODEL", spec.embedding_model) if spec.supports_embeddings else None,
        rerank_model=_override(name, "RERANK_MODEL", spec.rerank_model) if spec.supports_reranking else None,
    )


def live_provider_model(name: str) -> str:
    """The chat model the live tests use for a provider."""
    return _override(name, "MODEL", get_spec(name).default_model) or ""
