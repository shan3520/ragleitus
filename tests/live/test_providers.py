"""Each configured provider, for real: keys, chat, embeddings, reranking and judging.

See conftest.py for how to run these and which variables they read.
"""

from __future__ import annotations

import asyncio
import math

import pytest

from app.services import rag_evaluation
from app.services.chat_service import build_prompt, extract_citations
from app.services.evaluators import EvaluationInput, JudgeModel
from app.services.llm import ChatMessage, ProviderError, complete, create_provider
from app.services.llm.embeddings import ProviderEmbedder
from app.services.llm.rerank import ProviderReranker
from app.services.provider_validation import verify_provider_key
from app.services.retrieval import RetrievedChunk
from tests.live.providers import live_provider_model

QUESTION = "What does error E-4711 mean?"
PASSAGES = [
    "Error E-4711 means the upstream certificate expired. Renew the certificate to clear it.",
    "Employees receive 25 days of annual leave per calendar year.",
]

pytestmark = pytest.mark.live


def _sources() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(i, i, title, 1, text, 1.0, i, i)
        for i, (title, text) in enumerate(zip(["errors", "hr"], PASSAGES), start=1)
    ]


def test_the_key_is_accepted(live):
    check = asyncio.run(verify_provider_key(live.name, live.key, live.base_url))
    assert check.valid, check.detail


# Keys in each provider's format that no provider will accept.
MADE_UP_KEYS = {
    "openai": "sk-ragforgeLiveTestNotARealKey0000000000",
    "anthropic": "sk-ant-ragforge-live-test-not-a-real-key-0000",
    "gemini": "AIzaRagforgeLiveTestNotARealKey00000000",
    "groq": "gsk_ragforgeLiveTestNotARealKey0000000000000000000",
    "openrouter": "sk-or-v1-ragforgelivetestnotarealkey000000000000000000000000",
    "nvidia": "nvapi-ragforgeLiveTestNotARealKey00000000000000000000000000",
    "together": "ragforgelivetestnotarealkey0000000000000000000000000000000000",
    "mistral": "RagforgeLiveTestNotARealKey00000",
}


# Providers whose key check is known to accept any key (see the README).
# Strict xfails: once a gap is fixed the test fails, so the entry is removed.
KNOWN_KEY_CHECK_GAPS: dict[str, str] = {}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(name, marks=pytest.mark.xfail(reason=KNOWN_KEY_CHECK_GAPS[name], strict=True))
        if name in KNOWN_KEY_CHECK_GAPS else name
        for name in MADE_UP_KEYS
    ],
)
def test_a_made_up_key_is_rejected_as_a_bad_key_and_never_echoed(name):
    """Needs no key of yours: checks how each provider refuses one, which the app relies on."""
    spec_model = live_provider_model(name)
    key = MADE_UP_KEYS[name]
    check = asyncio.run(verify_provider_key(name, key))
    if check.unreachable and "Could not reach" in check.detail:
        pytest.skip(check.detail)
    assert not check.valid and not check.unreachable, check.detail
    assert check.detail.endswith("rejected the key."), check.detail
    # A chat call with it fails as an auth error, and the key is not in the message.
    with pytest.raises(ProviderError) as exc:
        asyncio.run(complete(create_provider(name, key), [ChatMessage("user", "Hi")], spec_model, 16))
    assert exc.value.is_auth_error, exc.value.message
    assert key not in exc.value.message


def test_a_streamed_answer_reports_text_and_usage(live):
    # Reasoning models (gpt-oss on Groq, Gemini 2.5) count their reasoning in
    # max_tokens: with 64, gpt-oss-120b sometimes ran out before any answer, and
    # with 256 so did NVIDIA's nemotron-3-super-120b-a12b (1 run in 6). Chat allows 16000.
    async def collect():
        events = []
        async for event in live.provider().stream(build_prompt([], "Reply with the single word: ready", []), live.model, 1024):
            events.append(event)
        return events

    events = asyncio.run(collect())
    deltas = [e for e in events if e.kind == "delta"]
    done = [e for e in events if e.kind == "done"]
    assert deltas and len(done) == 1 and events[-1] is done[0]
    assert "".join(d.text for d in deltas).strip()
    usage = done[0].usage
    if live.name != "custom":  # self-hosted servers may not report usage
        assert usage.prompt_tokens and usage.prompt_tokens > 0, usage
        assert usage.completion_tokens and usage.completion_tokens > 0, usage


def test_an_answer_uses_and_cites_the_passages(live):
    sources = _sources()
    result = asyncio.run(complete(live.provider(), build_prompt([], QUESTION, sources), live.model, 400))
    assert "certificate" in result.text.lower(), result.text
    citations = extract_citations(result.text, sources)
    assert citations and citations[0]["document_title"] == "errors", result.text


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def test_embeddings_put_the_matching_passage_closest(live):
    if not live.embedding_model:
        pytest.skip(f"{live.name} offers no embeddings (or LIVE_CUSTOM_EMBEDDING_MODEL is not set)")
    embedder = ProviderEmbedder(live.name, live.key, live.embedding_model, live.base_url)
    documents = embedder.embed_documents(PASSAGES)
    query = embedder.embed_query(QUESTION)
    assert len(documents) == 2 and len(query) == len(documents[0]) == embedder.dimension
    assert _cosine(query, documents[0]) > _cosine(query, documents[1])
    assert all(call.error is None for call in embedder.calls)


def test_reranking_puts_the_matching_passage_first(live):
    if not live.rerank_model:
        pytest.skip(f"{live.name} offers no reranking (or LIVE_CUSTOM_RERANK_MODEL is not set)")
    reranker = ProviderReranker(live.name, live.key, live.rerank_model, live.base_url)
    scores = reranker.rerank(QUESTION, PASSAGES)
    assert len(scores) == 2 and scores[0] > scores[1], scores


def test_the_built_in_judge_scores_a_faithful_answer(live):
    judge = JudgeModel(live.name, live.provider(), live.model)
    item = EvaluationInput(
        question=QUESTION,
        answer="It means the upstream certificate expired [1].",
        contexts=PASSAGES[:1],
        reference="The upstream certificate expired.",
    )
    scores = asyncio.run(rag_evaluation.score(item, judge, "builtin", None))
    metrics = [scores.faithfulness, scores.answer_relevancy, scores.context_precision]
    if live.name != "custom":  # a small self-hosted model may leave recall out
        metrics.append(scores.context_recall)
    for value in metrics:
        assert value is not None and 0 <= value <= 1, scores
    assert scores.faithfulness >= 0.5, scores
