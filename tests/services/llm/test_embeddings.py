import json

import httpx
import pytest

from app.core.config import settings
from app.services.llm import ProviderError
from app.services.llm.embeddings import BATCH_SIZE, ProviderEmbedder
from app.services.llm.url_guard import PRIVATE_URL_MESSAGE

KEY = "sk-secret-embedding-key-1234"


def _openai_handler(requests, dimension=3, usage=True):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request, body))
        # Returned out of order: the client must sort by index.
        data = [{"index": i, "embedding": [float(i + 1)] * dimension} for i in range(len(body["input"]))][::-1]
        payload = {"data": data}
        if usage:
            payload["usage"] = {"prompt_tokens": 7}
        return httpx.Response(200, json=payload)

    return handler


def test_openai_compatible_embeddings_in_batches_and_order():
    requests = []
    embedder = ProviderEmbedder("openai", KEY, "text-embedding-3-small", transport=httpx.MockTransport(_openai_handler(requests)))

    texts = [f"text {i}" for i in range(BATCH_SIZE + 2)]
    vectors = embedder.embed_documents(texts)

    assert len(vectors) == len(texts)
    assert vectors[0] == [1.0, 1.0, 1.0] and vectors[BATCH_SIZE] == [1.0, 1.0, 1.0] and vectors[1] == [2.0, 2.0, 2.0]
    assert embedder.dimension == 3
    assert embedder.model_name == "openai/text-embedding-3-small"
    assert [len(body["input"]) for _, body in requests] == [BATCH_SIZE, 2]
    request, body = requests[0]
    assert str(request.url) == "https://api.openai.com/v1/embeddings"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert body["model"] == "text-embedding-3-small" and "input_type" not in body
    assert [c.usage.prompt_tokens for c in embedder.calls] == [7, 7]
    assert all(c.error is None for c in embedder.calls)


def test_nvidia_says_whether_it_embeds_a_passage_or_a_query():
    requests = []
    embedder = ProviderEmbedder("nvidia", KEY, "nvidia/nv-embedqa-e5-v5", transport=httpx.MockTransport(_openai_handler(requests)))
    embedder.embed_documents(["a passage"])
    embedder.embed_query("a question")
    assert [body["input_type"] for _, body in requests] == ["passage", "query"]


def test_gemini_batch_embed_with_task_types_and_key_in_a_header():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request, body))
        return httpx.Response(200, json={"embeddings": [{"values": [0.5, 0.25]} for _ in body["requests"]]})

    embedder = ProviderEmbedder("gemini", "AIza" + "x" * 30, "gemini-embedding-001", transport=httpx.MockTransport(handler))
    assert embedder.embed_documents(["one", "two"]) == [[0.5, 0.25], [0.5, 0.25]]
    assert embedder.embed_query("q") == [0.5, 0.25]

    request, body = requests[0]
    assert request.url.path.endswith("/models/gemini-embedding-001:batchEmbedContents")
    assert "key" not in request.url.params
    assert request.headers["x-goog-api-key"].startswith("AIza")
    assert body["requests"][0] == {
        "model": "models/gemini-embedding-001", "content": {"parts": [{"text": "one"}]}, "taskType": "RETRIEVAL_DOCUMENT",
    }
    assert requests[1][1]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    # Gemini reports no token usage; telemetry estimates it from the text.
    assert embedder.calls[0].usage.prompt_tokens is None and embedder.calls[0].text == "one\ntwo"


def test_provider_errors_are_readable_and_never_contain_the_key():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}})

    embedder = ProviderEmbedder("openai", KEY, "text-embedding-3-small", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as exc:
        embedder.embed_query("q")
    assert exc.value.status_code == 401
    assert "Incorrect API key provided" in exc.value.message
    assert KEY not in exc.value.message
    assert embedder.calls[0].error is exc.value


def test_connection_errors_do_not_show_the_url():
    def handler(request):
        raise httpx.ConnectError("failed to connect to https://api.openai.com/v1/embeddings", request=request)

    embedder = ProviderEmbedder("openai", KEY, "text-embedding-3-small", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as exc:
        embedder.embed_query("q")
    assert exc.value.message == "Could not reach OpenAI (ConnectError)"


@pytest.mark.parametrize(
    "payload",
    [
        {"data": [{"index": 0, "embedding": []}]},
        {"data": [{"index": 0, "embedding": ["a", "b"]}]},
        {"data": []},
        {"data": "nope"},
        {"something": "else"},
    ],
)
def test_malformed_responses_are_rejected(payload):
    embedder = ProviderEmbedder(
        "openai", KEY, "m", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    with pytest.raises(ProviderError, match="unexpected response"):
        embedder.embed_query("q")


def test_vectors_of_another_size_are_rejected():
    sizes = iter([3, 4])

    def handler(request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * next(sizes)}]})

    embedder = ProviderEmbedder("openai", KEY, "m", transport=httpx.MockTransport(handler))
    embedder.embed_query("first")
    with pytest.raises(ProviderError, match="expected 3"):
        embedder.embed_query("second")


def test_a_self_hosted_server_on_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_provider_urls", False)
    called = []
    embedder = ProviderEmbedder(
        "custom", "none", "nomic-embed-text", "http://127.0.0.1:11434/v1",
        transport=httpx.MockTransport(lambda request: called.append(request) or httpx.Response(200)),
    )
    with pytest.raises(ProviderError) as exc:
        embedder.embed_query("q")
    assert exc.value.message == PRIVATE_URL_MESSAGE
    assert called == []


def test_a_self_hosted_servers_error_body_is_not_shown(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_provider_urls", True)
    embedder = ProviderEmbedder(
        "custom", "none", "nomic-embed-text", "http://localhost:11434/v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="internal secrets")),
    )
    with pytest.raises(ProviderError) as exc:
        embedder.embed_query("q")
    assert exc.value.message == "OpenAI-compatible (self-hosted) returned HTTP 500"


def test_providers_without_embeddings_and_missing_models_are_refused():
    with pytest.raises(ProviderError, match="does not offer embeddings"):
        ProviderEmbedder("anthropic", KEY, "anything")
    with pytest.raises(ProviderError, match="Choose an embedding model"):
        ProviderEmbedder("custom", "none", "", "https://example.com/v1")
