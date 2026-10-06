"""Reranking through a provider's API, with the user's own key.

A reranker reads the question and each candidate passage together and
scores how well the passage answers it, which is sharper than comparing
embeddings. Two wire formats cover the providers that offer one:

- Cohere-style `POST {base}/rerank` with {model, query, documents} returning
  {results: [{index, relevance_score}]}: Together AI, and self-hosted servers
  such as vLLM, Infinity or LocalAI;
- NVIDIA's `POST https://ai.api.nvidia.com/v1/retrieval/<model>/reranking`
  with {model, query: {text}, passages: [{text}]} returning
  {rankings: [{index, logit}], usage}. NVIDIA retires these models (and their
  URLs answer 410); nvidia/llama-nemotron-rerank-vl-1b-v2 was current on
  2026-10-06.

Like ProviderEmbedder, this is synchronous, notes every call in `calls` for
telemetry, and never puts the key (or, for user-supplied URLs, the response
body) in an error message.
"""

from __future__ import annotations

import time

import httpx

from app.core.config import settings
from app.services.llm.base import ProviderError, Usage
from app.services.llm.embeddings import EmbeddingCall
from app.services.llm.http import _error_text, retry_after_seconds
from app.services.llm.registry import get_spec
from app.services.llm.url_guard import ensure_public_url_sync

NVIDIA_RERANK_BASE_URL = "https://ai.api.nvidia.com/v1/retrieval"


class ProviderReranker:
    """A Reranker (see app.services.rerankers) backed by a provider's API."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        spec = get_spec(provider)
        if not spec.supports_reranking:
            raise ProviderError(f"{spec.label} does not offer reranking.", status_code=400)
        if not model:
            raise ProviderError("Choose a reranking model.", status_code=400)
        url = base_url or spec.base_url
        if not url:
            raise ProviderError(f"provider {provider!r} needs a base URL", status_code=400)
        self.provider = provider
        self.model = model
        self.model_name = f"{provider}/{model}"
        self.calls: list[EmbeddingCall] = []
        self._spec = spec
        self._api_key = api_key
        self._base_url = url.rstrip("/")
        self._transport = transport
        self._user_url = spec.requires_base_url

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        """A relevance score for each passage, in the order given (higher is better)."""
        if not passages:
            return []
        started = time.perf_counter()
        try:
            if self._user_url:
                ensure_public_url_sync(self._base_url)
            if self._spec.rerank_format == "nvidia":
                scores = self._nvidia(query, passages)
            else:
                scores = self._cohere(query, passages)
        except ProviderError as exc:
            self._note(started, query, passages, exc)
            raise
        except httpx.HTTPError as exc:
            error = ProviderError(f"Could not reach {self._spec.label} ({type(exc).__name__})")
            self._note(started, query, passages, error)
            raise error from None
        self._note(started, query, passages)
        return scores

    def _note(self, started: float, query: str, passages: list[str], error: ProviderError | None = None) -> None:
        text = "\n".join([query, *passages])
        self.calls.append(EmbeddingCall((time.perf_counter() - started) * 1000, Usage(), text, error))

    def _post(self, url: str, body: dict) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        with httpx.Client(timeout=settings.llm_timeout_seconds, transport=self._transport) as client:
            response = client.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            retry_after = retry_after_seconds(response.headers)
            if self._user_url:
                raise ProviderError(
                    f"{self._spec.label} returned HTTP {response.status_code}",
                    status_code=response.status_code, retry_after=retry_after,
                )
            raise ProviderError(
                f"{self._spec.label} returned HTTP {response.status_code}: {_error_text(response)}",
                status_code=response.status_code, retry_after=retry_after,
            )
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError(f"{self._spec.label} returned a response that is not JSON") from None
        return payload

    def _scores(self, items, count: int, score_keys: tuple[str, ...]) -> list[float]:
        bad = ProviderError(f"{self._spec.label} returned an unexpected response")
        if not isinstance(items, list):
            raise bad
        scores: list[float | None] = [None] * count
        for item in items:
            if not isinstance(item, dict):
                raise bad
            index = item.get("index")
            score = next((item[k] for k in score_keys if isinstance(item.get(k), (int, float))), None)
            if not isinstance(index, int) or not 0 <= index < count or score is None:
                raise bad
            scores[index] = float(score)
        if any(s is None for s in scores):
            raise bad  # every passage must be scored
        return scores  # type: ignore[return-value]

    def _cohere(self, query: str, passages: list[str]) -> list[float]:
        body = {"model": self.model, "query": query, "documents": passages, "top_n": len(passages), "return_documents": False}
        payload = self._post(f"{self._base_url}/rerank", body)
        # Cohere, Together and vLLM answer {results: [...]}; some servers a bare list.
        items = payload.get("results") if isinstance(payload, dict) else payload
        return self._scores(items, len(passages), ("relevance_score", "score"))

    def _nvidia(self, query: str, passages: list[str]) -> list[float]:
        # The URL names the model with "." spelled "_": nvidia/llama-3.2-x -> nvidia/llama-3_2-x.
        url = f"{NVIDIA_RERANK_BASE_URL}/{self.model.replace('.', '_')}/reranking"
        body = {
            "model": self.model,
            "query": {"text": query},
            "passages": [{"text": p} for p in passages],
            "truncate": "END",
        }
        payload = self._post(url, body)
        items = payload.get("rankings") if isinstance(payload, dict) else None
        return self._scores(items, len(passages), ("logit", "score"))
