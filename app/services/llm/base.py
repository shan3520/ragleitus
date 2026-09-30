"""Provider-neutral types for chat completion.

Every adapter turns a list of `ChatMessage` into a stream of `StreamEvent`s:
zero or more text deltas followed by exactly one `done` event carrying token
usage. `complete` is the same call with the deltas joined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class StreamEvent:
    kind: Literal["delta", "done"]
    text: str = ""
    usage: Usage = field(default_factory=Usage)
    # Model that actually served the request, when the provider reports it.
    model: str | None = None
    # Why generation stopped, normalised where possible ("stop", "length", "refusal", ...).
    finish_reason: str | None = None


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage
    model: str | None = None
    finish_reason: str | None = None


class ProviderError(Exception):
    """A provider call failed.

    `message` is safe to show to the user: adapters build it from the status
    code and the provider's error text, never from request headers, so it
    cannot contain the API key.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    @property
    def is_auth_error(self) -> bool:
        return self.status_code in (401, 403)


class ChatProvider(Protocol):
    name: str

    def stream(self, messages: list[ChatMessage], model: str, max_tokens: int) -> AsyncIterator[StreamEvent]:
        ...

    async def list_models(self) -> list[str]:
        ...


async def complete(provider: ChatProvider, messages: list[ChatMessage], model: str, max_tokens: int) -> Completion:
    """Run a streamed call to completion and join the deltas."""
    parts: list[str] = []
    usage = Usage()
    served_model = None
    finish_reason = None
    async for event in provider.stream(messages, model, max_tokens):
        if event.kind == "delta":
            parts.append(event.text)
        else:
            usage = event.usage
            served_model = event.model
            finish_reason = event.finish_reason
    return Completion(text="".join(parts), usage=usage, model=served_model, finish_reason=finish_reason)


def split_system(messages: list[ChatMessage]) -> tuple[str, list[ChatMessage]]:
    """Separate system messages (joined) from the conversation turns."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    return system, [m for m in messages if m.role != "system"]
