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


JUDGE_REPLY = (
    '{"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 0.5, '
    '"context_recall": 0.6, "rationale": "Fake judge."}'
)


class ScriptedProvider(FakeProvider):
    """Answers like a RAG model and judges like the LLM judge: judge prompts
    get `judge_reply`; other prompts get "<prefix> <first passage> [1]" (or
    `reply` when there is no passage). `fail_when(messages)` makes a call fail."""

    def __init__(self, prefix: str = "Answer:", judge_reply: str = JUDGE_REPLY, fail_when=None, **kwargs):
        super().__init__(**kwargs)
        self.prefix = prefix
        self.judge_reply = judge_reply
        self.fail_when = fail_when

    async def stream(self, messages, model, max_tokens):
        self.calls.append({"messages": messages, "model": model, "max_tokens": max_tokens})
        if self.fail_when and self.fail_when(messages):
            raise ProviderError("Fake provider is down", 503)
        system = messages[0].content if messages and messages[0].role == "system" else ""
        if "impartial evaluator" in system:
            text = self.judge_reply
        else:
            import re

            passage = re.search(r"\[1\] \([^)]*\)\n(.+)", system)
            text = f"{self.prefix} {passage.group(1).strip()} [1]" if passage else self.reply
        yield StreamEvent(kind="delta", text=text)
        yield StreamEvent(kind="done", usage=self.usage, model=model, finish_reason="stop")


def instance_of(schema: dict, root: dict | None = None, name: str = ""):
    """A value that satisfies a JSON schema, as a model would answer it:
    statements supported ("yes", 1), nothing evasive (noncommittal 0)."""
    root = root or schema
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        return instance_of(root.get("$defs", {}).get(ref, {}), root, name)
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            options = [s for s in schema[key] if s.get("type") != "null"] or schema[key]
            return instance_of(options[0], root, name)
    if "enum" in schema:
        return "yes" if "yes" in schema["enum"] else schema["enum"][0]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        return {k: instance_of(v, root, k) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        return [instance_of(schema.get("items", {}), root, name)]
    if kind == "integer":
        return 0 if "noncommittal" in name else 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    if "verdict" in name:
        return "yes"
    return f"A {name or 'value'}."


class SchemaJudgeProvider(ScriptedProvider):
    """A judge that answers Ragas/DeepEval prompts: when the system prompt
    carries a JSON schema (see evaluators.base), the reply is an instance of
    it; `bad_replies` replies come first as unreadable text."""

    def __init__(self, bad_replies: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.bad_replies = bad_replies

    async def stream(self, messages, model, max_tokens):
        import json

        system = messages[0].content if messages and messages[0].role == "system" else ""
        marker = "matches this JSON schema, and nothing else:\n"
        if marker not in system:
            async for event in super().stream(messages, model, max_tokens):
                yield event
            return
        self.calls.append({"messages": messages, "model": model, "max_tokens": max_tokens})
        if self.bad_replies:
            self.bad_replies -= 1
            text = "Sorry, here are my thoughts in prose."
        else:
            text = json.dumps(instance_of(json.loads(system.split(marker, 1)[1])))
        yield StreamEvent(kind="delta", text=text)
        yield StreamEvent(kind="done", usage=self.usage, model=model, finish_reason="stop")
