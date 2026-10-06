"""Adapter for the Google Gemini API (generateContent / streamGenerateContent)."""

from __future__ import annotations

from typing import AsyncIterator

import httpx

from app.services.llm.base import ChatMessage, StreamEvent, Usage, split_system
from app.services.llm.http import iter_sse_json, make_client, raise_for_status, transport_error

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

_FINISH_REASONS = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "refusal"}


def _output_tokens(metadata: dict) -> int | None:
    """Tokens billed as output: the answer plus, for thinking models, the thoughts.

    Gemini reports thinking separately (thoughtsTokenCount) but bills it as
    output, and leaves candidatesTokenCount out when the answer is empty.
    """
    answer, thoughts = metadata.get("candidatesTokenCount"), metadata.get("thoughtsTokenCount")
    if answer is None and thoughts is None:
        return None
    return (answer or 0) + (thoughts or 0)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, *, transport: httpx.AsyncBaseTransport | None = None):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        # Sent as a header rather than the ?key= query parameter so it never
        # appears in URLs that end up in logs or exception messages.
        return {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}

    async def stream(self, messages: list[ChatMessage], model: str, max_tokens: int) -> AsyncIterator[StreamEvent]:
        system, turns = split_system(messages)
        body: dict = {
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in turns
            ],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        usage = Usage()
        served_model = None
        finish_reason = None
        url = f"{self._base_url}/models/{model}:streamGenerateContent"
        try:
            async with make_client(self._transport) as client:
                async with client.stream("POST", url, params={"alt": "sse"}, headers=self._headers(), json=body) as response:
                    await raise_for_status(response, self.name)
                    async for chunk in iter_sse_json(response):
                        served_model = chunk.get("modelVersion") or served_model
                        metadata = chunk.get("usageMetadata")
                        if metadata:
                            usage = Usage(
                                prompt_tokens=metadata.get("promptTokenCount"),
                                completion_tokens=_output_tokens(metadata),
                            )
                        for candidate in chunk.get("candidates") or []:
                            for part in (candidate.get("content") or {}).get("parts") or []:
                                if part.get("text") and not part.get("thought"):
                                    yield StreamEvent(kind="delta", text=part["text"])
                            if candidate.get("finishReason"):
                                reason = candidate["finishReason"]
                                finish_reason = _FINISH_REASONS.get(reason, reason.lower())
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
        return [m["name"].removeprefix("models/") for m in payload.get("models", []) if "name" in m]
