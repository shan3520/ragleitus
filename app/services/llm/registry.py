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


PROVIDERS: dict[str, ProviderSpec] = {
    spec.name: spec
    for spec in [
        ProviderSpec(
            "openai", "OpenAI", "openai_compatible", "gpt-4o-mini",
            base_url="https://api.openai.com/v1", key_pattern=re.compile(r"^sk-[A-Za-z0-9_\-]{8,}$"),
        ),
        ProviderSpec("anthropic", "Anthropic", "anthropic", "claude-opus-5-5", key_pattern=re.compile(r"^sk-ant-[A-Za-z0-9_\-]{8,}$")),
        ProviderSpec("gemini", "Google Gemini", "gemini", "gemini-2.5-flash", base_url=GEMINI_BASE_URL, key_pattern=re.compile(r"^AIza[0-9A-Za-z\-_]{20,}$")),
        ProviderSpec("groq", "Groq", "openai_compatible", "llama-3.3-70b-versatile", base_url="https://api.groq.com/openai/v1"),
        ProviderSpec("openrouter", "OpenRouter", "openai_compatible", "openai/gpt-4o-mini", base_url="https://openrouter.ai/api/v1"),
        ProviderSpec("nvidia", "NVIDIA NIM", "openai_compatible", "meta/llama-3.1-70b-instruct", base_url="https://integrate.api.nvidia.com/v1"),
        ProviderSpec("together", "Together AI", "openai_compatible", "meta-llama/Llama-3.3-70B-Instruct-Turbo", base_url="https://api.together.xyz/v1"),
        ProviderSpec("mistral", "Mistral AI", "openai_compatible", "mistral-small-latest", base_url="https://api.mistral.ai/v1", stream_usage_option=False),
        ProviderSpec(
            "custom", "OpenAI-compatible (self-hosted)", "openai_compatible", "",
            stream_usage_option=False, requires_base_url=True,
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
    return OpenAICompatibleProvider(name, api_key, url, stream_usage_option=spec.stream_usage_option)


# Signature shared by create_provider and the fakes tests inject in its place.
ProviderFactory = Callable[[str, str, "str | None"], ChatProvider]
