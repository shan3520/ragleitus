"""Adapter for the OpenAI chat-completions API and the many services that copy it
(Groq, OpenRouter, NVIDIA NIM, Together AI, Mistral, and self-hosted servers
such as Ollama, LM Studio or vLLM)."""

from __future__ import annotations

from typing import AsyncIterator

import httpx

from app.services.llm.base import ChatMessage, StreamEvent, Usage, ProviderError
from app.services.llm.http import iter_sse_json, make_client, raise_for_status, transport_error


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        api_key: str,
        base_url: str,
        *,
        stream_usage_option: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.name = name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._stream_usage_option = stream_usage_option
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def stream(self, messages: list[ChatMessage], model: str, max_tokens: int) -> AsyncIterator[StreamEvent]:
        body: dict = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "stream": True,
        }
        if self._stream_usage_option:
            # Without this, OpenAI omits token usage from streamed responses.
            body["stream_options"] = {"include_usage": True}

        usage = Usage()
        served_model = None
        finish_reason = None
        try:
            async with make_client(self._transport) as client:
                async with client.stream(
                    "POST", f"{self._base_url}/chat/completions", headers=self._headers(), json=body
                ) as response:
                    await raise_for_status(response, self.name)
                    async for chunk in iter_sse_json(response):
                        if "error" in chunk:
                            error = chunk["error"]
                            message = error.get("message") if isinstance(error, dict) else str(error)
                            raise ProviderError(f"{self.name} stream error: {message}")
                        served_model = chunk.get("model") or served_model
                        if chunk.get("usage"):
                            usage = Usage(
                                prompt_tokens=chunk["usage"].get("prompt_tokens"),
                                completion_tokens=chunk["usage"].get("completion_tokens"),
                            )
                        for choice in chunk.get("choices") or []:
                            text = (choice.get("delta") or {}).get("content")
                            if text:
                                yield StreamEvent(kind="delta", text=text)
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from None

        yield StreamEvent(kind="done", usage=usage, model=served_model, finish_reason=finish_reason)

    async def list_models(self) -> list[str]:
        try:
            async with make_client(self._transport) as client:
                response = await client.get(f"{self._base_url}/models", headers=self._headers())
                await raise_for_status(response, self.name)
                payload = response.json()
        except httpx.HTTPError as exc:
            raise transport_error(self.name, exc) from None
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        return [item["id"] for item in data if isinstance(item, dict) and "id" in item]
