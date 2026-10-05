"""Embeddings through a provider's API, with the user's own key.

Two wire formats cover the providers that offer embeddings:

- OpenAI-compatible `POST {base}/embeddings` (OpenAI, Mistral, Together AI,
  NVIDIA NIM and self-hosted servers such as Ollama, LM Studio or vLLM);
- Gemini `POST {base}/models/{model}:batchEmbedContents`.

Indexing and retrieval are synchronous (worker threads and Celery tasks), so
this client is too. The vector size is learned from the first response.

Every call is noted in `calls` (latency, tokens, error) so the caller can
record it in telemetry with its own database session. Error messages never
contain the key; for user-supplied URLs they leave out the response body as
well, as the chat adapters do.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.llm.base import ProviderError, Usage
from app.services.llm.http import _error_text
from app.services.llm.registry import get_spec
from app.services.llm.url_guard import ensure_public_url_sync

# Texts per request; well under every provider's limit (Gemini allows 100).
BATCH_SIZE = 64


@dataclass(frozen=True)
class EmbeddingCall:
    latency_ms: float
    usage: Usage
    text: str
    error: ProviderError | None = None


class ProviderEmbedder:
    """An Embedder (see app.services.embeddings) backed by a provider's API."""

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
        if not spec.supports_embeddings:
            raise ProviderError(f"{spec.label} does not offer embeddings.", status_code=400)
        if not model:
            raise ProviderError("Choose an embedding model.", status_code=400)
        url = base_url or spec.base_url
        if not url:
            raise ProviderError(f"provider {provider!r} needs a base URL", status_code=400)
        self.provider = provider
        self.model = model
        # Names the vector collection, so the same model from two providers
        # never shares one.
        self.model_name = f"{provider}/{model}"
        self.dimension: int | None = None
        self.calls: list[EmbeddingCall] = []
        self._spec = spec
        self._api_key = api_key
        self._base_url = url.rstrip("/")
        self._transport = transport
        # A user-supplied URL is checked before every request, and its error
        # bodies are not shown (see url_guard.py).
        self._user_url = spec.requires_base_url

    # -- Embedder interface

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(self._embed(texts[start:start + BATCH_SIZE], query=False))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], query=True)[0]

    # -- wire formats

    def _embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        if not texts:
            return []
        started = time.perf_counter()
        usage = Usage()
        try:
            if self._user_url:
                ensure_public_url_sync(self._base_url)
            if self._spec.kind == "gemini":
                vectors = self._gemini(texts, query)
            else:
                vectors, usage = self._openai(texts, query)
            self._check(vectors, len(texts))
        except ProviderError as exc:
            self._note(started, usage, texts, exc)
            raise
        except httpx.HTTPError as exc:
            # The exception type is enough; its text can include the request URL.
            error = ProviderError(f"Could not reach {self._spec.label} ({type(exc).__name__})")
            self._note(started, usage, texts, error)
            raise error from None
        self._note(started, usage, texts)
        return vectors

    def _note(self, started: float, usage: Usage, texts: list[str], error: ProviderError | None = None) -> None:
        self.calls.append(EmbeddingCall((time.perf_counter() - started) * 1000, usage, "\n".join(texts), error))

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        with httpx.Client(timeout=settings.llm_timeout_seconds, transport=self._transport) as client:
            response = client.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            if self._user_url:
                raise ProviderError(f"{self._spec.label} returned HTTP {response.status_code}", status_code=response.status_code)
            raise ProviderError(
                f"{self._spec.label} returned HTTP {response.status_code}: {_error_text(response)}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError(f"{self._spec.label} returned a response that is not JSON") from None
        if not isinstance(payload, dict):
            raise ProviderError(f"{self._spec.label} returned an unexpected response")
        return payload

    def _openai(self, texts: list[str], query: bool) -> tuple[list[list[float]], Usage]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body: dict = {"model": self.model, "input": texts, "encoding_format": "float"}
        if self._spec.embedding_input_type:
            body["input_type"] = "query" if query else "passage"
        payload = self._post(f"{self._base_url}/embeddings", headers, body)
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderError(f"{self._spec.label} returned an unexpected response")
        try:
            ordered = sorted(data, key=lambda item: item.get("index", 0))
            vectors = [item["embedding"] for item in ordered]
        except (AttributeError, KeyError, TypeError):
            raise ProviderError(f"{self._spec.label} returned an unexpected response") from None
        reported = payload.get("usage")
        tokens = reported.get("prompt_tokens") if isinstance(reported, dict) else None
        return vectors, Usage(prompt_tokens=tokens, completion_tokens=0 if tokens is not None else None)

    def _gemini(self, texts: list[str], query: bool) -> list[list[float]]:
        # The key goes in a header, never in the URL (see gemini.py).
        headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
        task = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"
        body = {
            "requests": [
                {"model": f"models/{self.model}", "content": {"parts": [{"text": t}]}, "taskType": task}
                for t in texts
            ]
        }
        payload = self._post(f"{self._base_url}/models/{self.model}:batchEmbedContents", headers, body)
        try:
            return [item["values"] for item in payload["embeddings"]]
        except (KeyError, TypeError):
            raise ProviderError(f"{self._spec.label} returned an unexpected response") from None

    def _check(self, vectors: list, expected: int) -> None:
        bad = ProviderError(f"{self._spec.label} returned an unexpected response")
        if len(vectors) != expected:
            raise bad
        for vector in vectors:
            if not isinstance(vector, list) or not vector or not all(isinstance(v, (int, float)) for v in vector):
                raise bad
            if self.dimension is None:
                self.dimension = len(vector)
            elif len(vector) != self.dimension:
                raise ProviderError(
                    f"{self._spec.label} returned vectors of {len(vector)} numbers, expected {self.dimension}"
                )
