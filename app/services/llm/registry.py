"""Supported providers and how to build an adapter for each."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal

from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.base import ChatProvider
from app.services.llm.gemini import DEFAULT_BASE_URL as GEMINI_BASE_URL
from app.services.llm.gemini import GeminiProvider
from app.services.llm.openai_compatible import OpenAICompatibleProvider
from app.services.llm.url_guard import ensure_public_url


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    kind: Literal["openai_compatible", "anthropic", "gemini"]
    default_model: str
    base_url: str | None = None
    # Pre-check applied before calling the provider; None accepts any non-empty key.
    key_pattern: re.Pattern | None = None
    # Whether the endpoint accepts stream_options.include_usage.
    stream_usage_option: bool = True
    # Whether the user supplies the base URL (self-hosted servers).
    requires_base_url: bool = False
    # Where the key check lists models; it must need the key, or any key passes.
    models_path: str = "/models"
    # For a provider whose model list needs no key: a free GET that does, which
    # the key check calls first.
    key_check_url: str | None = None
    # Suggested model for embedding documents through this provider. None:
    # the provider offers no embeddings API. "": supported, but the user must
    # name the model (self-hosted servers).
    embedding_model: str | None = None
    # NVIDIA's retrieval embedders need to know whether they embed a passage or a query.
    embedding_input_type: bool = False
    # Suggested reranking model (see llm.rerank), with the same None / "" meaning.
    rerank_model: str | None = None
    rerank_format: Literal["cohere", "nvidia"] = "cohere"
    # Why the provider is not offered for new keys, if it isn't. Keys already
    # stored keep working; the live tests (tests/live) still run it, so it can
    # be verified and offered again.
    unavailable: str | None = None

    @property
    def offered(self) -> bool:
        return self.unavailable is None

    @property
    def supports_embeddings(self) -> bool:
        return self.embedding_model is not None

    @property
    def supports_reranking(self) -> bool:
        return self.rerank_model is not None


PROVIDERS: dict[str, ProviderSpec] = {
    spec.name: spec
    for spec in [
        ProviderSpec(
            "openai", "OpenAI", "openai_compatible", "gpt-4o-mini",
            base_url="https://api.openai.com/v1", key_pattern=re.compile(r"^sk-[A-Za-z0-9_\-]{8,}$"),
            embedding_model="text-embedding-3-small",
        ),
        ProviderSpec("anthropic", "Anthropic", "anthropic", "claude-opus-5-5", key_pattern=re.compile(r"^sk-ant-[A-Za-z0-9_\-]{8,}$")),
        # Standard keys start AIza; AI Studio has issued "auth keys" (AQ.) since 28 May 2026.
        ProviderSpec(
            "gemini", "Google Gemini", "gemini", "gemini-2.5-flash", base_url=GEMINI_BASE_URL,
            key_pattern=re.compile(r"^(AIza[0-9A-Za-z\-_]{20,}|AQ\.[0-9A-Za-z\-_.]{20,})$"), embedding_model="gemini-embedding-001",
        ),
        ProviderSpec("groq", "Groq", "openai_compatible", "openai/gpt-oss-120b", base_url="https://api.groq.com/openai/v1"),
        # OpenRouter's /models is public; /models/user (the same list, filtered by the
        # account's settings) is the one that needs the key.
        ProviderSpec(
            "openrouter", "OpenRouter", "openai_compatible", "openai/gpt-4o-mini", base_url="https://openrouter.ai/api/v1",
            models_path="/models/user",
        ),
        # Defaults confirmed live on 2026-10-06; NVIDIA retired the earlier ones in 2026.
        # /v1/models answers without a key, so the key check first lists the
        # account's cloud functions, which needs one (401/403 otherwise).
        ProviderSpec(
            "nvidia", "NVIDIA NIM", "openai_compatible", "nvidia/nemotron-3-super-120b-a12b",
            base_url="https://integrate.api.nvidia.com/v1",
            key_check_url="https://api.nvcf.nvidia.com/v2/nvcf/functions",
            embedding_model="nvidia/nemotron-3-embed-1b", embedding_input_type=True,
            rerank_model="nvidia/llama-nemotron-rerank-vl-1b-v2", rerank_format="nvidia",
        ),
        ProviderSpec(
            "together", "Together AI", "openai_compatible", "meta-llama/Llama-3.3-70B-Instruct-Turbo", base_url="https://api.together.xyz/v1",
            embedding_model="BAAI/bge-base-en-v1.5", rerank_model="Salesforce/Llama-Rank-V1",
        ),
        ProviderSpec(
            "mistral", "Mistral AI", "openai_compatible", "mistral-small-latest", base_url="https://api.mistral.ai/v1",
            stream_usage_option=False, embedding_model="mistral-embed",
        ),
        ProviderSpec(
            "custom", "OpenAI-compatible (self-hosted)", "openai_compatible", "",
            stream_usage_option=False, requires_base_url=True, embedding_model="", rerank_model="",
        ),
    ]
}


class UnknownProviderError(ValueError):
    pass


def get_spec(name: str) -> ProviderSpec:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise UnknownProviderError(name) from None


def create_provider(name: str, api_key: str, base_url: str | None = None) -> ChatProvider:
    spec = get_spec(name)
    if spec.kind == "anthropic":
        return AnthropicProvider(api_key)
    if spec.kind == "gemini":
        return GeminiProvider(api_key, base_url or spec.base_url)
    url = base_url or spec.base_url
    if not url:
        raise ValueError(f"provider {name!r} needs a base URL")
    if spec.requires_base_url:
        # The URL comes from the user: refuse private addresses and don't echo response bodies.
        return OpenAICompatibleProvider(
            name, api_key, url, stream_usage_option=spec.stream_usage_option,
            url_guard=ensure_public_url, expose_error_body=False,
        )
    return OpenAICompatibleProvider(
        name, api_key, url, stream_usage_option=spec.stream_usage_option, models_path=spec.models_path,
        key_check_url=spec.key_check_url,
    )


# Signature shared by create_provider and the fakes tests inject in its place.
ProviderFactory = Callable[[str, str, "str | None"], ChatProvider]
