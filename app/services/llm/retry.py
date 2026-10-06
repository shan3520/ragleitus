"""Retrying provider calls that failed for a passing reason.

Experiments make many calls in a row, several at a time, so a provider's
rate limit (429) or a moment of overload (503, 529) is expected rather than
exceptional. `RetryingProvider` waits and tries such a call again, as the
provider asks (Retry-After) or with exponential backoff. Only a call that
failed before producing any text is retried, so an answer is never repeated.

Chat does not use it: a person is waiting there, and an error is quicker.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import AsyncIterator, Awaitable, Callable

from app.services.llm.base import ChatMessage, ChatProvider, ProviderError, StreamEvent
from app.services.llm.registry import ProviderFactory

logger = logging.getLogger(__name__)

ATTEMPTS = 4  # the first try and three retries
MAX_WAIT_SECONDS = 30.0
# A provider asking for a longer wait than this has run out of a quota that will
# not come back during the run (Gemini's free tier: 20 requests a day per model,
# then "retry in 18h"); waiting out the retries would only delay the error.
GIVE_UP_AFTER_SECONDS = 300.0


def worth_retrying(exc: ProviderError) -> bool:
    return exc.is_retryable and (exc.retry_after is None or exc.retry_after <= GIVE_UP_AFTER_SECONDS)


def backoff_seconds(exc: ProviderError, retry: int) -> float:
    """How long to wait before retry number `retry` (0-based)."""
    if exc.retry_after is not None:
        return min(MAX_WAIT_SECONDS, exc.retry_after)
    # 1, 2, 4 seconds, each with up to 50% jitter so parallel calls spread out.
    base = 2.0**retry
    return min(MAX_WAIT_SECONDS, base * (1 + random.random() / 2))


class RetryingProvider:
    """A provider whose calls are retried on rate limits and transient errors."""

    def __init__(
        self,
        inner: ChatProvider,
        attempts: int = ATTEMPTS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.inner = inner
        self.attempts = attempts
        self._sleep = sleep

    @property
    def name(self) -> str:
        return self.inner.name

    def __getattr__(self, attribute):
        return getattr(self.inner, attribute)

    async def stream(self, messages: list[ChatMessage], model: str, max_tokens: int) -> AsyncIterator[StreamEvent]:
        for attempt in range(self.attempts):
            produced = False
            try:
                async for event in self.inner.stream(messages, model, max_tokens):
                    produced = True
                    yield event
                return
            except ProviderError as exc:
                if produced or not worth_retrying(exc) or attempt == self.attempts - 1:
                    raise
                wait = backoff_seconds(exc, attempt)
                logger.info(
                    "Provider call will be retried",
                    extra={"provider": self.inner.name, "status": exc.status_code, "wait_seconds": round(wait, 2)},
                )
                await self._sleep(wait)

    async def list_models(self) -> list[str]:
        return await self.inner.list_models()


def with_retries(factory: ProviderFactory) -> ProviderFactory:
    """`factory`, building providers whose calls are retried."""

    def build(*args, **kwargs) -> ChatProvider:
        return RetryingProvider(factory(*args, **kwargs))

    return build


class RetryingReranker:
    """A reranker (see app.services.rerankers) whose calls are retried the same way."""

    def __init__(self, inner, attempts: int = ATTEMPTS, sleep: Callable[[float], None] = time.sleep):
        self.inner = inner
        self.attempts = attempts
        self._sleep = sleep

    def __getattr__(self, attribute):
        return getattr(self.inner, attribute)

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        for attempt in range(self.attempts):
            try:
                return self.inner.rerank(query, passages)
            except ProviderError as exc:
                if not worth_retrying(exc) or attempt == self.attempts - 1:
                    raise
                self._sleep(backoff_seconds(exc, attempt))
        raise AssertionError("unreachable")
