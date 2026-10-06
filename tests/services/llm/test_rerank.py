import json

import httpx
import pytest

from app.core.config import settings
from app.services.llm.base import ProviderError
from app.services.llm.rerank import ProviderReranker
from app.services.llm.url_guard import PRIVATE_URL_MESSAGE

KEY = "tgp-secret-key-123"


def _cohere_handler(requests, results=None):
    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        scores = results or [{"index": i, "relevance_score": 1 - i / 10} for i in reversed(range(len(body["documents"])))]
        return httpx.Response(200, json={"id": "r1", "results": scores})

    return handler


def test_together_uses_the_cohere_style_rerank_endpoint():
    requests = []
    reranker = ProviderReranker("together", KEY, "Salesforce/Llama-Rank-V1", transport=httpx.MockTransport(_cohere_handler(requests)))

    scores = reranker.rerank("What is E-4711?", ["first", "second", "third"])

    # Results come back best first; scores are returned in the passages' order.
    assert scores == [1.0, 0.9, 0.8]
    request = requests[0]
    assert str(request.url) == "https://api.together.xyz/v1/rerank"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content) == {
        "model": "Salesforce/Llama-Rank-V1", "query": "What is E-4711?", "documents": ["first", "second", "third"],
        "top_n": 3, "return_documents": False,
    }
    assert len(reranker.calls) == 1 and reranker.calls[0].error is None


def test_nvidia_uses_its_reranking_endpoint_and_logits():
    # An older model, for the URL rule: "." in the model name is spelled "_".
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"rankings": [{"index": 1, "logit": 4.5}, {"index": 0, "logit": -2.0}]})

    reranker = ProviderReranker("nvidia", "nvapi-x", "nvidia/llama-3.2-nv-rerankqa-1b-v2", transport=httpx.MockTransport(handler))
    assert reranker.rerank("q", ["a", "b"]) == [-2.0, 4.5]
    request = requests[0]
    assert str(request.url) == "https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-3_2-nv-rerankqa-1b-v2/reranking"
    assert json.loads(request.content) == {
        "model": "nvidia/llama-3.2-nv-rerankqa-1b-v2", "query": {"text": "q"},
        "passages": [{"text": "a"}, {"text": "b"}], "truncate": "END",
    }


def test_nvidia_s_current_default_model_with_its_real_response():
    from app.services.llm import get_spec

    requests = []

    def handler(request):
        requests.append(request)
        # nvidia/llama-nemotron-rerank-vl-1b-v2's real answer for the live tests' question and passages.
        return httpx.Response(200, json={"rankings": [{"index": 1, "logit": 4.0703125}, {"index": 0, "logit": -6.94921875}],
                                         "usage": {"prompt_tokens": 50, "total_tokens": 50}})

    model = get_spec("nvidia").rerank_model
    assert model == "nvidia/llama-nemotron-rerank-vl-1b-v2"
    reranker = ProviderReranker("nvidia", "nvapi-x", model, transport=httpx.MockTransport(handler))
    assert reranker.rerank("q", ["leave", "certificate"]) == [-6.94921875, 4.0703125]
    assert str(requests[0].url) == "https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-nemotron-rerank-vl-1b-v2/reranking"


def test_a_self_hosted_server_answering_a_bare_list_with_scores(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_provider_urls", True)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[{"index": 0, "score": 0.2}, {"index": 1, "score": 0.7}])

    reranker = ProviderReranker("custom", "", "BAAI/bge-reranker-base", "http://localhost:7997/v1/", transport=httpx.MockTransport(handler))
    assert reranker.rerank("q", ["a", "b"]) == [0.2, 0.7]
    assert str(requests[0].url) == "http://localhost:7997/v1/rerank"
    assert "Authorization" not in requests[0].headers  # no key for a server that needs none


@pytest.mark.parametrize(
    "payload",
    [
        {"results": [{"index": 0, "relevance_score": 0.5}]},  # one passage left unscored
        {"results": [{"index": 5, "relevance_score": 0.5}, {"index": 0, "relevance_score": 0.1}]},
        {"results": [{"index": 0}, {"index": 1}]},
        {"results": "nope"},
        {"data": []},
    ],
)
def test_unexpected_responses_are_errors(payload):
    reranker = ProviderReranker(
        "together", KEY, "m", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    with pytest.raises(ProviderError, match="unexpected response"):
        reranker.rerank("q", ["a", "b"])
    assert reranker.calls[0].error is not None


def test_errors_carry_the_status_and_retry_after_but_never_the_key():
    reranker = ProviderReranker(
        "together", KEY, "m",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "3"}, json={"error": {"message": "slow down"}})
        ),
    )
    with pytest.raises(ProviderError) as exc:
        reranker.rerank("q", ["a"])
    assert exc.value.status_code == 429 and exc.value.retry_after == 3.0
    assert "slow down" in exc.value.message and KEY not in exc.value.message


def test_a_self_hosted_server_on_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_provider_urls", False)
    called = []
    reranker = ProviderReranker(
        "custom", "none", "m", "http://127.0.0.1:7997/v1",
        transport=httpx.MockTransport(lambda request: called.append(request) or httpx.Response(200)),
    )
    with pytest.raises(ProviderError) as exc:
        reranker.rerank("q", ["a"])
    assert exc.value.message == PRIVATE_URL_MESSAGE and called == []


def test_a_self_hosted_servers_error_body_is_not_shown(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_provider_urls", True)
    reranker = ProviderReranker(
        "custom", "none", "m", "http://localhost:7997/v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="internal secrets")),
    )
    with pytest.raises(ProviderError) as exc:
        reranker.rerank("q", ["a"])
    assert "internal secrets" not in exc.value.message


def test_providers_without_reranking_or_a_model_are_refused():
    with pytest.raises(ProviderError, match="does not offer reranking"):
        ProviderReranker("openai", KEY, "x")
    with pytest.raises(ProviderError, match="Choose a reranking model"):
        ProviderReranker("custom", "none", "", "https://example.com/v1")


def test_nothing_to_rerank_makes_no_call():
    reranker = ProviderReranker("together", KEY, "m", transport=httpx.MockTransport(lambda r: pytest.fail("called")))
    assert reranker.rerank("q", []) == [] and reranker.calls == []
