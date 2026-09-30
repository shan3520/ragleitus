"""Chat with your documents.

A turn has two halves:

1. `prepare_turn` (synchronous, inside the request): checks the conversation
   and the provider choice, retrieves passages, builds the prompt and saves
   the user's message. Anything the user got wrong fails here, before any
   tokens are spent.
2. `stream_turn` (async): calls the provider, yields answer tokens as they
   arrive, then saves the assistant message with its citations and records
   telemetry. It uses its own database session, because a streamed response
   outlives the request's session.

The prompt numbers the passages [1]..[k] and asks the model to cite them;
the [n] markers in the answer are resolved back to documents and pages.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.conversation import Conversation, Message
from app.services import telemetry
from app.services.llm import ChatMessage, ChatProvider, ProviderError, ProviderFactory, Usage, create_provider, get_spec
from app.services.llm.pricing import estimate_cost_usd
from app.services.prompt_template import format_prompt
from app.services.provider_key import MissingProviderKeyError, create_user_provider, list_provider_keys
from app.services.retrieval import RetrievedChunk, retrieve

SYSTEM_PROMPT = """You are RAGForge, an assistant that answers questions using the numbered context passages below, taken from the user's documents.

Rules:
- Base your answer only on the passages. Do not use outside knowledge for facts.
- Cite the passage for every claim with its number in square brackets, like [1] or [2][3].
- If the passages do not contain the answer, say that you could not find it in the documents.
- Answer in the language of the question.

Context passages:
{context}"""

NO_CONTEXT = "(No passages matched this question.)"
_CITATION_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


class ChatError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConversationNotFoundError(ChatError):
    status_code = 404


class ProviderChoiceError(ChatError):
    status_code = 400


@dataclass(frozen=True)
class PreparedTurn:
    user_id: int
    conversation_id: int
    user_message_id: int
    provider_name: str
    model: str
    provider: ChatProvider
    prompt: list[ChatMessage]
    sources: list[RetrievedChunk]


# ---------------------------------------------------------------- conversations


def create_conversation(session: Session, user_id: int, title: str | None = None, provider: str | None = None, model: str | None = None) -> Conversation:
    if provider is not None:
        _check_provider_name(provider)
    conversation = Conversation(user_id=user_id, title=(title or "New conversation")[:255], provider=provider, model=model)
    session.add(conversation)
    session.flush()
    return conversation


def list_conversations(session: Session, user_id: int) -> list[Conversation]:
    return (
        session.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .all()
    )


def get_conversation(session: Session, user_id: int, conversation_id: int) -> Conversation:
    conversation = (
        session.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .first()
    )
    if conversation is None:
        raise ConversationNotFoundError("Conversation not found")
    return conversation


def delete_conversation(session: Session, user_id: int, conversation_id: int) -> None:
    session.delete(get_conversation(session, user_id, conversation_id))
    session.flush()


# ---------------------------------------------------------------- prompt


def _check_provider_name(provider: str) -> None:
    try:
        get_spec(provider)
    except ValueError:
        raise ProviderChoiceError(f"Unknown provider '{provider}'")


def resolve_provider_choice(
    session: Session, user_id: int, conversation: Conversation, provider: str | None, model: str | None
) -> tuple[str, str]:
    """Pick the provider and model: the request's, else the conversation's, else the
    user's only configured provider with its default model."""
    chosen = provider or conversation.provider
    if chosen is None:
        configured = [pk.provider for pk in list_provider_keys(session, user_id)]
        if not configured:
            raise ProviderChoiceError("Add an API key for an LLM provider first (POST /api/provider-keys).")
        if len(configured) > 1:
            raise ProviderChoiceError(f"Choose a provider: you have keys for {', '.join(configured)}.")
        chosen = configured[0]
    _check_provider_name(chosen)

    chosen_model = model or (conversation.model if chosen == conversation.provider else None) or get_spec(chosen).default_model
    if not chosen_model:
        raise ProviderChoiceError(f"Provider '{chosen}' has no default model; pass a model name.")
    return chosen, chosen_model


def format_context(sources: list[RetrievedChunk]) -> str:
    if not sources:
        return NO_CONTEXT
    blocks = []
    for number, source in enumerate(sources, start=1):
        location = f", page {source.page_number}" if source.page_number else ""
        blocks.append(f"[{number}] ({source.document_title}{location})\n{source.content}")
    return "\n\n".join(blocks)


def build_prompt(history: list[Message], question: str, sources: list[RetrievedChunk]) -> list[ChatMessage]:
    system = format_prompt(SYSTEM_PROMPT, {"context": format_context(sources)})
    turns = [ChatMessage(m.role, m.content) for m in history if m.role in ("user", "assistant")]
    return [ChatMessage("system", system), *turns, ChatMessage("user", question)]


def extract_citations(answer: str, sources: list[RetrievedChunk]) -> list[dict]:
    """Sources cited as [n] in the answer, in order of first citation."""
    cited: list[dict] = []
    seen: set[int] = set()
    for match in _CITATION_RE.finditer(answer):
        for raw in match.group(1).split(","):
            number = int(raw)
            if number in seen or not 1 <= number <= len(sources):
                continue
            seen.add(number)
            cited.append(_source_dict(number, sources[number - 1]))
    return cited


def _source_dict(number: int, source: RetrievedChunk) -> dict:
    return {
        "number": number,
        "document_id": source.document_id,
        "document_title": source.document_title,
        "page_number": source.page_number,
        "chunk_id": source.chunk_id,
        "snippet": source.content[:300],
    }


# ---------------------------------------------------------------- turns


def prepare_turn(
    session: Session,
    user_id: int,
    conversation_id: int,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    document_ids: list[int] | None = None,
    factory: ProviderFactory = create_provider,
    retriever: Callable[..., list[RetrievedChunk]] = retrieve,
) -> PreparedTurn:
    content = content.strip()
    if not content:
        raise ChatError("Message must not be empty")
    conversation = get_conversation(session, user_id, conversation_id)
    provider_name, model_name = resolve_provider_choice(session, user_id, conversation, provider, model)
    try:
        chat_provider = create_user_provider(session, user_id, provider_name, factory)
    except MissingProviderKeyError:
        raise ProviderChoiceError(f"No API key stored for provider '{provider_name}'.")

    history_limit = settings.chat_history_turns * 2
    history = list(conversation.messages)[-history_limit:] if history_limit else []
    sources = retriever(session, user_id, content, document_ids=document_ids)
    prompt = build_prompt(history, content, sources)

    user_message = Message(conversation_id=conversation.id, role="user", content=content)
    session.add(user_message)
    if not conversation.messages or conversation.title == "New conversation":
        conversation.title = content[:80]
    conversation.provider = provider_name
    conversation.model = model_name
    session.flush()

    return PreparedTurn(
        user_id=user_id,
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        provider_name=provider_name,
        model=model_name,
        provider=chat_provider,
        prompt=prompt,
        sources=sources,
    )


async def stream_turn(turn: PreparedTurn, session_factory: Callable[[], Session] = SessionLocal) -> AsyncIterator[tuple[str, dict]]:
    """Yield ("token", {...}) events, then ("citations", {...}) and ("done", {...}),
    or a single ("error", {...}) if the provider call fails."""
    started = time.perf_counter()
    ttft_ms = None
    parts: list[str] = []
    usage = Usage()
    served_model = None
    finish_reason = None
    prompt_text = "\n\n".join(m.content for m in turn.prompt)

    try:
        async for event in turn.provider.stream(turn.prompt, turn.model, settings.llm_max_output_tokens):
            if event.kind == "delta":
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - started) * 1000
                parts.append(event.text)
                yield "token", {"text": event.text}
            else:
                usage, served_model, finish_reason = event.usage, event.model, event.finish_reason
    except ProviderError as exc:
        session = session_factory()
        try:
            telemetry.record_llm_call(
                session, user_id=turn.user_id, operation="chat", provider=turn.provider_name, model=turn.model,
                latency_ms=(time.perf_counter() - started) * 1000, error=exc, conversation_id=turn.conversation_id,
                prompt_text=prompt_text,
            )
            session.commit()
        finally:
            session.close()
        yield "error", {"message": exc.message, "status_code": exc.status_code}
        return

    latency_ms = (time.perf_counter() - started) * 1000
    answer = "".join(parts)
    citations = extract_citations(answer, turn.sources)
    model_name = served_model or turn.model

    session = session_factory()
    try:
        event = telemetry.record_llm_call(
            session, user_id=turn.user_id, operation="chat", provider=turn.provider_name, model=model_name,
            latency_ms=latency_ms, ttft_ms=ttft_ms, usage=usage, prompt_text=prompt_text, completion_text=answer,
            conversation_id=turn.conversation_id,
        )
        message = Message(
            conversation_id=turn.conversation_id,
            role="assistant",
            content=answer,
            citations=citations,
            context=[_source_dict(i, s) | {"content": s.content} for i, s in enumerate(turn.sources, start=1)],
            provider=turn.provider_name,
            model=model_name,
            prompt_tokens=event.prompt_tokens,
            completion_tokens=event.completion_tokens,
            latency_ms=round(latency_ms, 2),
            finish_reason=finish_reason,
        )
        session.add(message)
        session.flush()
        event.message_id = message.id
        session.commit()
        message_id = message.id
        prompt_tokens, completion_tokens, cost = event.prompt_tokens, event.completion_tokens, event.cost_usd
    finally:
        session.close()

    yield "citations", {"citations": citations}
    yield "done", {
        "message_id": message_id,
        "provider": turn.provider_name,
        "model": model_name,
        "finish_reason": finish_reason,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": cost if cost is not None else estimate_cost_usd(model_name, Usage(prompt_tokens, completion_tokens)),
        "latency_ms": round(latency_ms, 2),
        "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
    }


class ChatProviderError(ChatError):
    status_code = 502


async def run_turn(turn: PreparedTurn, session_factory: Callable[[], Session] = SessionLocal) -> dict:
    """Non-streaming variant: the full answer with citations and usage."""
    answer_parts: list[str] = []
    result: dict = {}
    async for name, data in stream_turn(turn, session_factory):
        if name == "token":
            answer_parts.append(data["text"])
        elif name == "citations":
            result["citations"] = data["citations"]
        elif name == "done":
            result.update(data)
        elif name == "error":
            raise ChatProviderError(data["message"])
    return {"content": "".join(answer_parts), **result}
