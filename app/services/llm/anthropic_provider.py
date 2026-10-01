"""Adapter for Anthropic's Messages API, via the official `anthropic` SDK."""

from __future__ import annotations

from typing import AsyncIterator

import anthropic

from app.core.config import settings
from app.services.llm.base import ChatMessage, ProviderError, StreamEvent, Usage, split_system

# Models that accept the server-side refusal fallback. When a safety
# classifier declines a request on one of these, the API re-runs it on a
# suitable fallback model inside the same call instead of returning an empty
# refusal.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_FINISH_REASONS = {"end_turn": "stop", "max_tokens": "length", "stop_sequence": "stop", "refusal": "refusal"}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, *, client: anthropic.AsyncAnthropic | None = None):
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=settings.llm_timeout_seconds,
        )

    def _open_stream(self, system: str, turns: list[ChatMessage], model: str, max_tokens: int):
        params: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in turns],
        }
        if system:
            params["system"] = system
        if model in _FALLBACK_MODELS:
            return self._client.beta.messages.stream(betas=[_FALLBACK_BETA], fallbacks="default", **params)
        return self._client.messages.stream(**params)

    async def stream(self, messages: list[ChatMessage], model: str, max_tokens: int) -> AsyncIterator[StreamEvent]:
        system, turns = split_system(messages)
        try:
            async with self._open_stream(system, turns, model, max_tokens) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield StreamEvent(kind="delta", text=text)
                final = await stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"anthropic returned HTTP {exc.status_code}: {exc.message}", status_code=exc.status_code) from None
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"Could not reach anthropic ({type(exc).__name__})") from None

        yield StreamEvent(
            kind="done",
            usage=Usage(prompt_tokens=final.usage.input_tokens, completion_tokens=final.usage.output_tokens),
            model=final.model,
            finish_reason=_FINISH_REASONS.get(final.stop_reason, final.stop_reason),
        )

    async def list_models(self) -> list[str]:
        try:
            page = await self._client.models.list(limit=100)
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"anthropic returned HTTP {exc.status_code}: {exc.message}", status_code=exc.status_code) from None
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"Could not reach anthropic ({type(exc).__name__})") from None
        return [model.id for model in page.data]
