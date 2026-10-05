import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_provider_factory
from app.db.database import get_db
from app.models.user import User
from app.services import chat_service
from app.services.llm import ProviderFactory

router = APIRouter(prefix="/api/conversations", tags=["chat"])


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    provider: str | None = None
    model: str | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    provider: str | None
    model: str | None
    prompt_version_id: int | None = None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    citations: list[dict] | None
    provider: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float | None
    finish_reason: str | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    provider: str | None = None
    model: str | None = None
    document_ids: list[int] | None = Field(default=None, description="Only search these documents")
    prompt_version_id: int | None = Field(
        default=None,
        description="Answer with this prompt-library version from now on (null: the built-in prompt). "
        "Leave out to keep the conversation's prompt.",
    )
    stream: bool = True


def _raise(exc: chat_service.ChatError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreate, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    try:
        conversation = chat_service.create_conversation(session, user.id, payload.title, payload.provider, payload.model)
    except chat_service.ChatError as exc:
        _raise(exc)
    session.commit()
    return conversation


@router.get("", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    return chat_service.list_conversations(session, user.id)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    try:
        return chat_service.get_conversation(session, user.id, conversation_id)
    except chat_service.ChatError as exc:
        _raise(exc)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    try:
        chat_service.delete_conversation(session, user.id, conversation_id)
    except chat_service.ChatError as exc:
        _raise(exc)
    session.commit()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post(
    "/{conversation_id}/messages",
    responses={200: {"description": "JSON answer, or a text/event-stream when `stream` is true"}},
)
async def send_message(
    conversation_id: int,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    factory: ProviderFactory = Depends(get_provider_factory),
):
    """Ask a question about your documents.

    With `stream: true` (the default) the response is server-sent events:
    `sources` (the passages given to the model, and `warnings` such as
    documents that could only be searched by keyword), then `token` events with
    answer text, then `citations` and finally `done` with usage, cost and
    latency. A provider failure ends the stream with an `error` event.
    With `stream: false` the same information comes back as one JSON object.
    """
    try:
        # Retrieval embeds the question and queries the database: blocking work.
        turn = await run_in_threadpool(
            chat_service.prepare_turn,
            session, user.id, conversation_id, payload.content,
            provider=payload.provider, model=payload.model, document_ids=payload.document_ids, factory=factory,
            prompt_version_id=(
                payload.prompt_version_id if "prompt_version_id" in payload.model_fields_set else chat_service.KEEP_PROMPT
            ),
        )
    except chat_service.ChatError as exc:
        _raise(exc)
    session.commit()

    sources = [
        {"number": i, "document_id": s.document_id, "document_title": s.document_title, "page_number": s.page_number}
        for i, s in enumerate(turn.sources, start=1)
    ]

    if not payload.stream:
        try:
            result = await chat_service.run_turn(turn)
        except chat_service.ChatError as exc:
            _raise(exc)
        return {"sources": sources, "warnings": turn.warnings, **result}

    async def events():
        yield _sse("sources", {"sources": sources, "warnings": turn.warnings})
        async for name, data in chat_service.stream_turn(turn):
            yield _sse(name, data)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
