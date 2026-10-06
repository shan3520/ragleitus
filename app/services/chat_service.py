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

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Callable

from sqlalchemy.orm import Session

from opentelemetry.trace import Status, StatusCode

from app.core import tracing
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
# Some models (OpenAI's gpt-oss, e.g. on Groq) cite with full-width brackets: 【1】.
_FULLWIDTH_CITATION_RE = re.compile(r"【\s*(\d+(?:\s*,\s*\d+)*)\s*】")
# The start of a full-width marker whose closing bracket has not arrived yet.
_PARTIAL_FULLWIDTH_RE = re.compile(r"【[\d\s,]{0,20}")


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
    # Retrieval problems the user should know about (documents searched by
    # keyword only because their embedding provider could not be used).
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- conversations


DEFAULT_TITLE = "New conversation"


def create_conversation(session: Session, user_id: int, title: str | None = None, provider: str | None = None, model: str | None = None) -> Conversation:
    if provider is not None:
        _check_provider_name(provider)
    conversation = Conversation(user_id=user_id, title=(title or DEFAULT_TITLE)[:255], provider=provider, model=model)
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


def answered_history(messages: list[Message], max_turns: int) -> list[Message]:
    """The last `max_turns` complete exchanges: a user message and the assistant answer right after it.

    A question whose answer failed or was interrupted has no answer stored. It
    is left out, so the prompt keeps alternating user/assistant, which
    Anthropic and Gemini require.
    """
    if max_turns <= 0:
        return []
    pairs: list[tuple[Message, Message]] = []
    for previous, current in zip(messages, messages[1:]):
        if previous.role == "user" and current.role == "assistant":
            pairs.append((previous, current))
    return [m for pair in pairs[-max_turns:] for m in pair]


def build_prompt(
    history: list[Message], question: str, sources: list[RetrievedChunk], template: str | None = None
) -> list[ChatMessage]:
    """The messages for the model: the system prompt with the passages (the
    built-in one, or a prompt-library template), the history and the question."""
    system = format_prompt(template or SYSTEM_PROMPT, {"context": format_context(sources), "question": question})
    turns = [ChatMessage(m.role, m.content) for m in history if m.role in ("user", "assistant")]
    return [ChatMessage("system", system), *turns, ChatMessage("user", question)]


def normalize_citations(text: str) -> str:
    """The text with full-width citation markers (【1】) written as [1]."""
    return _FULLWIDTH_CITATION_RE.sub(r"[\1]", text)


class CitationStream:
    """normalize_citations for streamed text, whose markers may be split across deltas.

    A possible marker start (【, 【1, ...) is held back until it closes or turns
    out not to be one; `flush` returns whatever is still held at the end.
    """

    def __init__(self) -> None:
        self._held = ""

    def feed(self, text: str) -> str:
        text, self._held = self._held + text, ""
        start = text.rfind("【")
        if start != -1 and _PARTIAL_FULLWIDTH_RE.fullmatch(text, start):
            text, self._held = text[:start], text[start:]
        return normalize_citations(text)

    def flush(self) -> str:
        held, self._held = self._held, ""
        return held


def extract_citations(answer: str, sources: list[RetrievedChunk]) -> list[dict]:
    """Sources cited as [n] (or 【n】) in the answer, in order of first citation."""
    cited: list[dict] = []
    seen: set[int] = set()
    for match in _CITATION_RE.finditer(normalize_citations(answer)):
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

# prepare_turn: keep the conversation's prompt choice.
KEEP_PROMPT = object()


class PromptVersionNotFoundError(ChatError):
    status_code = 404


def prompt_template(session: Session, user_id: int, version_id: int) -> str:
    """The template of a prompt-library version the user owns."""
    from app.models.prompt import Prompt, PromptVersion

    template = (
        session.query(PromptVersion.template)
        .join(Prompt, PromptVersion.prompt_id == Prompt.id)
        .filter(PromptVersion.id == version_id, Prompt.user_id == user_id)
        .scalar()
    )
    if template is None:
        raise PromptVersionNotFoundError("Prompt version not found")
    return template


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
    prompt_version_id: int | None | object = KEEP_PROMPT,
) -> PreparedTurn:
    """`prompt_version_id`: a prompt-library version to answer with from now
    on, None for the built-in prompt, or KEEP_PROMPT for the conversation's."""
    content = content.strip()
    if not content:
        raise ChatError("Message must not be empty")
    conversation = get_conversation(session, user_id, conversation_id)
    if prompt_version_id is not KEEP_PROMPT:
        if prompt_version_id is not None:
            prompt_template(session, user_id, prompt_version_id)  # must be the user's
        conversation.prompt_version_id = prompt_version_id
    template = prompt_template(session, user_id, conversation.prompt_version_id) if conversation.prompt_version_id else None
    provider_name, model_name = resolve_provider_choice(session, user_id, conversation, provider, model)
    try:
        chat_provider = create_user_provider(session, user_id, provider_name, factory)
    except MissingProviderKeyError:
        raise ProviderChoiceError(f"No API key stored for provider '{provider_name}'.")

    history = answered_history(list(conversation.messages), settings.chat_history_turns)
    warnings: list[str] = []
    sources = retriever(session, user_id, content, document_ids=document_ids, warnings=warnings)
    prompt = build_prompt(history, content, sources, template)

    user_message = Message(conversation_id=conversation.id, role="user", content=content)
    session.add(user_message)
    if conversation.title == DEFAULT_TITLE:
        conversation.title = content[:80]
    conversation.provider = provider_name
    conversation.model = model_name
    # Set explicitly: assigning unchanged values is not a change, so onupdate would not fire.
    conversation.updated_at = datetime.now(timezone.utc)
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
        warnings=warnings,
    )


def _record_failure(
    session_factory: Callable[[], Session], turn: PreparedTurn, prompt_text: str, latency_ms: float, exc: ProviderError
) -> None:
    session = session_factory()
    try:
        telemetry.record_llm_call(
            session, user_id=turn.user_id, operation="chat", provider=turn.provider_name, model=turn.model,
            latency_ms=latency_ms, error=exc, conversation_id=turn.conversation_id, prompt_text=prompt_text,
        )
        session.commit()
    finally:
        session.close()


def _store_answer(
    session_factory: Callable[[], Session],
    turn: PreparedTurn,
    prompt_text: str,
    answer: str,
    citations: list[dict],
    model_name: str,
    latency_ms: float,
    ttft_ms: float | None,
    usage: Usage,
    finish_reason: str | None,
) -> tuple[int, int | None, int | None, float | None]:
    """Save the assistant message and its telemetry row; returns (message_id, prompt_tokens, completion_tokens, cost)."""
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
        session.query(Conversation).filter(Conversation.id == turn.conversation_id).update(
            {Conversation.updated_at: datetime.now(timezone.utc)}, synchronize_session=False
        )
        session.commit()
        return message.id, event.prompt_tokens, event.completion_tokens, event.cost_usd
    finally:
        session.close()


async def stream_turn(turn: PreparedTurn, session_factory: Callable[[], Session] = SessionLocal) -> AsyncIterator[tuple[str, dict]]:
    """Yield ("token", {...}) events, then ("citations", {...}) and ("done", {...}),
    or a single ("error", {...}) if the provider call fails."""
    generation = tracing.start_span(
        "rag.generate",
        gen_ai__operation__name="chat", gen_ai__system=turn.provider_name, gen_ai__request__model=turn.model,
        user__id=str(turn.user_id), session__id=str(turn.conversation_id), rag__sources=len(turn.sources),
    )
    try:
        async for name, data in _stream_turn(turn, session_factory, generation):
            yield name, data
    finally:
        generation.end()


async def _stream_turn(turn: PreparedTurn, session_factory, generation) -> AsyncIterator[tuple[str, dict]]:
    started = time.perf_counter()
    ttft_ms = None
    parts: list[str] = []
    usage = Usage()
    served_model = None
    finish_reason = None
    prompt_text = "\n\n".join(m.content for m in turn.prompt)
    tracing.record_content(generation, prompt=prompt_text)
    citation_stream = CitationStream()

    try:
        async for event in turn.provider.stream(turn.prompt, turn.model, settings.llm_max_output_tokens):
            if event.kind == "delta":
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - started) * 1000
                text = citation_stream.feed(event.text)
                if text:
                    parts.append(text)
                    yield "token", {"text": text}
            else:
                usage, served_model, finish_reason = event.usage, event.model, event.finish_reason
        if held := citation_stream.flush():
            parts.append(held)
            yield "token", {"text": held}
    except ProviderError as exc:
        generation.set_status(Status(StatusCode.ERROR, exc.message))
        # Blocking database work runs in a thread so other streams keep flowing.
        await asyncio.to_thread(
            _record_failure, session_factory, turn, prompt_text, (time.perf_counter() - started) * 1000, exc
        )
        yield "error", {"message": exc.message, "status_code": exc.status_code}
        return

    latency_ms = (time.perf_counter() - started) * 1000
    answer = "".join(parts)
    citations = extract_citations(answer, turn.sources)
    model_name = served_model or turn.model

    message_id, prompt_tokens, completion_tokens, cost = await asyncio.to_thread(
        _store_answer, session_factory, turn, prompt_text, answer, citations, model_name,
        latency_ms, ttft_ms, usage, finish_reason,
    )

    tracing.set_attributes(
        generation,
        gen_ai__response__model=model_name, gen_ai__usage__input_tokens=prompt_tokens,
        gen_ai__usage__output_tokens=completion_tokens, gen_ai__response__finish_reasons=[finish_reason or "unknown"],
        rag__citations=len(citations), rag__ttft_ms=round(ttft_ms, 2) if ttft_ms is not None else None,
    )
    tracing.record_content(generation, completion=answer)
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
