import asyncio
import json

import httpx
import pytest

from app.services.llm import ChatMessage, ProviderError, complete
from app.services.llm.gemini import GeminiProvider


def _provider(handler):
    return GeminiProvider("AIza-secret", "https://gemini.example.test/v1beta", transport=httpx.MockTransport(handler))


def test_stream_maps_roles_system_instruction_and_usage():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        chunks = [
            {"candidates": [{"content": {"parts": [{"text": "Bon"}]}}], "modelVersion": "gemini-x-001"},
            {"candidates": [{"content": {"parts": [{"text": "jour"}]}, "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 3}},
        ]
        return httpx.Response(200, content="".join(f"data: {json.dumps(c)}\r\n\r\n" for c in chunks).encode())

    messages = [
        ChatMessage("system", "Answer in French."),
        ChatMessage("user", "Hello"),
        ChatMessage("assistant", "Salut"),
        ChatMessage("user", "Again"),
    ]
    result = asyncio.run(complete(_provider(handler), messages, "gemini-x", 100))

    assert seen["url"] == "https://gemini.example.test/v1beta/models/gemini-x:streamGenerateContent?alt=sse"
    assert seen["key"] == "AIza-secret"
    assert "key=" not in seen["url"]
    assert seen["body"]["systemInstruction"] == {"parts": [{"text": "Answer in French."}]}
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model", "user"]
    assert seen["body"]["generationConfig"] == {"maxOutputTokens": 100}
    assert result.text == "Bonjour"
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (9, 3)
    assert result.finish_reason == "stop"
    assert result.model == "gemini-x-001"


def test_thought_parts_are_not_returned_as_answer_text():
    def handler(request):
        chunk = {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": "Answer"}]}}]}
        return httpx.Response(200, content=f"data: {json.dumps(chunk)}\n\n".encode())

    result = asyncio.run(complete(_provider(handler), [ChatMessage("user", "Q")], "m", 10))
    assert result.text == "Answer"


def test_error_status():
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "API key not valid"}})

    with pytest.raises(ProviderError) as exc:
        asyncio.run(_provider(handler).list_models())
    assert exc.value.status_code == 400
    assert "AIza-secret" not in exc.value.message


def test_list_models_strips_prefix():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "models/gemini-a"}, {"name": "models/gemini-b"}]})

    assert asyncio.run(_provider(handler).list_models()) == ["gemini-a", "gemini-b"]
