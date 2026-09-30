"""Runs the real `anthropic` SDK against a mocked HTTP transport, so request
shape and SSE parsing are exercised without a network call."""

import asyncio
import json

import anthropic
import httpx2
import pytest

from app.services.llm import ChatMessage, ProviderError, complete
from app.services.llm.anthropic_provider import AnthropicProvider


def _sse(model="claude-opus-5-5", stop_reason="end_turn", text_parts=("Hel", "lo")) -> bytes:
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 42, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    ]
    events += [
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}})
        for t in text_parts
    ]
    events += [
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                           "usage": {"output_tokens": 7}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def _provider(handler):
    client = anthropic.AsyncAnthropic(
        api_key="sk-ant-secret",
        base_url="https://anthropic.example.test",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicProvider("sk-ant-secret", client=client)


def test_stream_request_shape_and_usage():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, content=_sse(), headers={"content-type": "text/event-stream"})

    messages = [ChatMessage("system", "Cite sources."), ChatMessage("user", "Question?")]
    result = asyncio.run(complete(_provider(handler), messages, "claude-opus-5-5", 2048))

    assert seen["path"] == "/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-ant-secret"
    assert "anthropic-version" in seen["headers"]
    assert seen["body"]["system"] == "Cite sources."
    assert seen["body"]["messages"] == [{"role": "user", "content": "Question?"}]
    assert seen["body"]["max_tokens"] == 2048
    assert seen["body"]["stream"] is True
    assert result.text == "Hello"
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (42, 7)
    assert result.finish_reason == "stop"
    assert result.model == "claude-opus-5-5"


def test_supported_models_opt_into_server_side_refusal_fallback():
    seen = {}

    def handler(request):
        seen["beta"] = request.headers.get("anthropic-beta", "")
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, content=_sse(), headers={"content-type": "text/event-stream"})

    asyncio.run(complete(_provider(handler), [ChatMessage("user", "Q")], "claude-opus-5-5", 100))
    assert "server-side-fallback-2026-07-01" in seen["beta"]
    assert seen["body"]["fallbacks"] == "default"


def test_other_models_do_not_send_fallbacks():
    seen = {}

    def handler(request):
        seen["beta"] = request.headers.get("anthropic-beta")
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, content=_sse(model="claude-haiku-4-5"), headers={"content-type": "text/event-stream"})

    asyncio.run(complete(_provider(handler), [ChatMessage("user", "Q")], "claude-haiku-4-5", 100))
    assert seen["beta"] is None
    assert "fallbacks" not in seen["body"]


def test_refusal_is_reported_as_finish_reason():
    def handler(request):
        return httpx2.Response(200, content=_sse(stop_reason="refusal", text_parts=()), headers={"content-type": "text/event-stream"})

    result = asyncio.run(complete(_provider(handler), [ChatMessage("user", "Q")], "claude-haiku-4-5", 100))
    assert result.finish_reason == "refusal"
    assert result.text == ""


def test_api_error_becomes_provider_error():
    def handler(request):
        return httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})

    with pytest.raises(ProviderError) as exc:
        asyncio.run(complete(_provider(handler), [ChatMessage("user", "Q")], "claude-haiku-4-5", 100))
    assert exc.value.status_code == 401
    assert "sk-ant-secret" not in exc.value.message


def test_list_models():
    def handler(request):
        assert request.url.path == "/v1/models"
        return httpx2.Response(200, json={
            "data": [{"id": "claude-opus-5-5", "type": "model", "display_name": "Claude Opus 5.5", "created_at": "2026-01-01T00:00:00Z"}],
            "has_more": False, "first_id": "claude-opus-5-5", "last_id": "claude-opus-5-5",
        })

    assert asyncio.run(_provider(handler).list_models()) == ["claude-opus-5-5"]
