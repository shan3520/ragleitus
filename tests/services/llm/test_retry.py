import asyncio

import pytest

from app.services.llm import ChatMessage, ProviderError, StreamEvent, Usage, complete
from app.services.llm import retry
from app.services.llm.retry import RetryingProvider, backoff_seconds, with_retries

MESSAGES = [ChatMessage(role="user", content="hi")]


class Flaky:
    """Fails with the given errors first, then answers."""

    name = "flaky"

    def __init__(self, errors, fail_after_text=False):
        self.errors = list(errors)
        self.fail_after_text = fail_after_text
        self.calls = 0

    async def stream(self, messages, model, max_tokens):
        self.calls += 1
        if self.fail_after_text:
            yield StreamEvent(kind="delta", text="partial ")
        if self.errors:
            raise self.errors.pop(0)
        yield StreamEvent(kind="delta", text="ok")
        yield StreamEvent(kind="done", usage=Usage(1, 1))

    async def list_models(self):
        return ["m"]


def _run(provider):
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    wrapped = RetryingProvider(provider, sleep=sleep)
    return wrapped, waits, (lambda: asyncio.run(complete(wrapped, MESSAGES, "m", 10)))


def test_rate_limits_and_overload_are_retried_until_an_answer(monkeypatch):
    monkeypatch.setattr(retry, "MAX_WAIT_SECONDS", 30.0)  # tests otherwise never wait
    provider = Flaky([ProviderError("429", 429, retry_after=2.5), ProviderError("503", 503)])
    _, waits, call = _run(provider)
    assert call().text == "ok"
    assert provider.calls == 3
    assert waits[0] == 2.5  # as the provider asked


def test_other_errors_are_not_retried():
    for error in (ProviderError("bad key", 401), ProviderError("bad request", 400), ProviderError("unreachable")):
        provider = Flaky([error])
        _, waits, call = _run(provider)
        with pytest.raises(ProviderError):
            call()
        assert provider.calls == 1 and waits == []


def test_it_gives_up_after_the_last_attempt():
    provider = Flaky([ProviderError("429", 429)] * 10)
    _, waits, call = _run(provider)
    with pytest.raises(ProviderError, match="429"):
        call()
    assert provider.calls == retry.ATTEMPTS and len(waits) == retry.ATTEMPTS - 1


def test_a_call_that_already_produced_text_is_not_repeated():
    provider = Flaky([ProviderError("503", 503)], fail_after_text=True)
    _, _, call = _run(provider)
    with pytest.raises(ProviderError):
        call()
    assert provider.calls == 1


def test_backoff_grows_is_capped_and_honours_retry_after(monkeypatch):
    monkeypatch.setattr(retry, "MAX_WAIT_SECONDS", 30.0)
    assert 1 <= backoff_seconds(ProviderError("x", 429), 0) <= 1.5
    assert 4 <= backoff_seconds(ProviderError("x", 429), 2) <= 6
    assert backoff_seconds(ProviderError("x", 429), 10) == 30.0
    assert backoff_seconds(ProviderError("x", 429, retry_after=3600), 0) == 30.0
    assert backoff_seconds(ProviderError("x", 429, retry_after=0.2), 0) == 0.2


def test_the_wrapper_looks_like_the_provider():
    built = []

    def factory(name, api_key, base_url=None):
        built.append((name, api_key, base_url))
        return Flaky([])

    provider = with_retries(factory)("openai", "sk-x", None)
    assert isinstance(provider, RetryingProvider) and provider.name == "flaky"
    assert asyncio.run(provider.list_models()) == ["m"]
    assert built == [("openai", "sk-x", None)]


def test_rerank_calls_are_retried_on_rate_limits_only():
    from app.services.llm.retry import RetryingReranker

    class Inner:
        provider, calls = "together", ["seen"]

        def __init__(self, errors):
            self.errors, self.asked = list(errors), 0

        def rerank(self, query, passages):
            self.asked += 1
            if self.errors:
                raise self.errors.pop(0)
            return [1.0] * len(passages)

    waits = []
    inner = Inner([ProviderError("429", 429, retry_after=0.5)])
    reranker = RetryingReranker(inner, sleep=waits.append)
    assert reranker.rerank("q", ["a", "b"]) == [1.0, 1.0] and inner.asked == 2 and waits == [0.0]
    assert reranker.provider == "together" and reranker.calls == ["seen"]  # looks like the inner one

    inner = Inner([ProviderError("bad", 400)])
    with pytest.raises(ProviderError):
        RetryingReranker(inner, sleep=waits.append).rerank("q", ["a"])
    assert inner.asked == 1
