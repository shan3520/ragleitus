"""In-process stand-ins for LLM providers, so no test makes a network call."""

from __future__ import annotations

from app.services.embeddings import FakeEmbedder
from app.services.llm import ChatMessage, ProviderError, StreamEvent, Usage
from app.services.llm.embeddings import EmbeddingCall


class FakeProvider:
    def __init__(
        self,
        name: str = "fake",
        reply: str = "A fake answer.",
        usage: Usage = Usage(prompt_tokens=100, completion_tokens=20),
        models: list[str] | None = None,
        error: ProviderError | None = None,
        served_model: str | None = None,
    ):
        self.name = name
        self.reply = reply
        self.usage = usage
        self.models = models if models is not None else ["fake-model"]
        self.error = error
        self.served_model = served_model
        self.calls: list[dict] = []

    async def stream(self, messages: list[ChatMessage], model: str, max_tokens: int):
        self.calls.append({"messages": messages, "model": model, "max_tokens": max_tokens})
        if self.error:
            raise self.error
        words = self.reply.split(" ")
        for i, word in enumerate(words):
            yield StreamEvent(kind="delta", text=word if i == len(words) - 1 else word + " ")
        yield StreamEvent(kind="done", usage=self.usage, model=self.served_model or model, finish_reason="stop")

    async def list_models(self) -> list[str]:
        if self.error:
            raise self.error
        return self.models


class FakeFactory:
    """Drop-in for `create_provider` that hands out one FakeProvider and records how it was built."""

    def __init__(self, provider: FakeProvider | None = None):
        self.provider = provider or FakeProvider()
        self.created: list[tuple[str, str, str | None]] = []

    def __call__(self, name: str, api_key: str, base_url: str | None = None):
        self.created.append((name, api_key, base_url))
        return self.provider


class FakeProviderEmbedder(FakeEmbedder):
    """Stands in for ProviderEmbedder: hashing vectors (a different size from
    the local fake, so a different collection), a provider name, and the same
    call log. With `fail`, every call raises it."""

    def __init__(self, provider: str = "openai", model: str = "fake-embed", dimension: int = 64, fail: Exception | None = None):
        super().__init__(dimension)
        self.provider = provider
        self.model = model
        self.model_name = f"{provider}/{model}"
        self.calls: list[EmbeddingCall] = []
        self.fail = fail

    def _note(self, texts: list[str]) -> None:
        if self.fail is not None:
            self.calls.append(EmbeddingCall(1.0, Usage(), "\n".join(texts), self.fail))
            raise self.fail
        self.calls.append(EmbeddingCall(1.0, Usage(prompt_tokens=3 * len(texts), completion_tokens=0), "\n".join(texts)))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._note(texts)
        return super().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        self._note([text])
        return super().embed_query(text)


def provider_embedder_factory(**kwargs):
    """An EmbedderFactory that builds FakeProviderEmbedders for the chosen provider and model."""
    built: list[FakeProviderEmbedder] = []

    def factory(session, user_id, choice):
        embedder = FakeProviderEmbedder(choice.provider, choice.model, **kwargs)
        built.append(embedder)
        return embedder

    factory.built = built
    return factory
