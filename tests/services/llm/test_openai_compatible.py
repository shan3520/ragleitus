import asyncio
import json

import httpx
import pytest

from app.services.llm import ChatMessage, ProviderError, complete
from app.services.llm.openai_compatible import OpenAICompatibleProvider


def _sse(*payloads) -> bytes:
    lines = [f"data: {json.dumps(p)}\n\n" for p in payloads] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def _provider(handler, **kwargs):
    return OpenAICompatibleProvider(
        "openai", "sk-secret-key", "https://api.example.test/v1", transport=httpx.MockTransport(handler), **kwargs
    )


def test_stream_sends_expected_request_and_parses_deltas_and_usage():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {"model": "gpt-4o-mini-2024", "choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 2}},
            ),
            headers={"content-type": "text/event-stream"},
        )

    messages = [ChatMessage("system", "Be brief."), ChatMessage("user", "Hi")]
    result = asyncio.run(complete(_provider(handler), messages, "gpt-4o-mini", 256))

    assert seen["url"] == "https://api.example.test/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-secret-key"
    assert seen["body"]["messages"] == [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}]
    assert seen["body"]["stream"] is True
    assert seen["body"]["stream_options"] == {"include_usage": True}
    assert seen["body"]["max_tokens"] == 256
    assert result.text == "Hello"
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 2
    assert result.model == "gpt-4o-mini-2024"
    assert result.finish_reason == "stop"


def test_stream_usage_option_can_be_disabled():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=_sse({"choices": [{"delta": {"content": "x"}}]}))

    asyncio.run(complete(_provider(handler, stream_usage_option=False), [ChatMessage("user", "Hi")], "m", 10))
    assert "stream_options" not in bodies[0]


def test_http_error_becomes_provider_error_without_the_key():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}})

    with pytest.raises(ProviderError) as exc:
        asyncio.run(complete(_provider(handler), [ChatMessage("user", "Hi")], "m", 10))
    assert exc.value.status_code == 401
    assert exc.value.is_auth_error
    assert "Incorrect API key provided" in exc.value.message
    assert "sk-secret-key" not in exc.value.message


def test_connection_error_becomes_provider_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(ProviderError) as exc:
        asyncio.run(complete(_provider(handler), [ChatMessage("user", "Hi")], "m", 10))
    assert exc.value.status_code is None


def test_error_inside_stream_is_raised():
    def handler(request):
        return httpx.Response(200, content=_sse({"error": {"message": "overloaded"}}))

    with pytest.raises(ProviderError, match="overloaded"):
        asyncio.run(complete(_provider(handler), [ChatMessage("user", "Hi")], "m", 10))


def test_list_models():
    def handler(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]})

    assert asyncio.run(_provider(handler).list_models()) == ["a", "b"]


def test_no_authorization_header_when_key_is_empty():
    headers = {}

    def handler(request):
        headers.update(request.headers)
        return httpx.Response(200, json={"data": []})

    provider = OpenAICompatibleProvider("custom", "", "http://localhost:11434/v1", transport=httpx.MockTransport(handler))
    asyncio.run(provider.list_models())
    assert "authorization" not in headers
