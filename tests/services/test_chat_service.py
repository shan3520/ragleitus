import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.conversation import Message
from app.models.telemetry_event import TelemetryEvent
from app.services import chat_service
from app.services.llm import ProviderError, StreamEvent, Usage
from app.services.provider_key import encrypt_key, save_provider_key
from app.services.retrieval import RetrievedChunk
from tests.fakes import FakeFactory, FakeProvider
from tests.helpers import make_user


def _source(n, title="Handbook", page=2):
    return RetrievedChunk(
        chunk_id=100 + n, document_id=10 + n, document_title=title, page_number=page,
        content=f"Passage {n} text.", score=0.1, dense_rank=n, keyword_rank=None,
    )


SOURCES = [_source(1), _source(2, title="Policy", page=None)]


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'chat.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    user = make_user(session)
    session.commit()
    yield factory, session, user.id
    session.close()


def _add_key(session, user_id, provider="openai"):
    save_provider_key(session, user_id, provider, encrypt_key("sk-test-12345678"))
    session.commit()


def test_extract_citations_resolves_markers_in_order_and_ignores_invalid_ones():
    answer = "Leave is 25 days [2]. Also [1][2], see [1, 2] and [7]."
    cited = chat_service.extract_citations(answer, SOURCES)
    assert [c["number"] for c in cited] == [2, 1]
    assert cited[0]["document_title"] == "Policy"
    assert cited[1]["page_number"] == 2


def test_full_width_citation_markers_are_read_as_ordinary_ones():
    # As gpt-oss-120b on Groq writes them.
    answer = "Error E‑4711 indicates that the upstream certificate has expired【1】, see also 【 1, 2 】."
    assert chat_service.normalize_citations(answer) == (
        "Error E‑4711 indicates that the upstream certificate has expired[1], see also [1, 2]."
    )
    assert [c["number"] for c in chat_service.extract_citations(answer, SOURCES)] == [1, 2]
    assert chat_service.normalize_citations("【note】 and 【】 stay as written") == "【note】 and 【】 stay as written"


def test_a_citation_stream_rewrites_markers_split_across_deltas():
    stream = chat_service.CitationStream()
    out = [stream.feed(t) for t in ["It expired", "【", "1", "】.", " Also 【2", ",3】", " and 【no", "te】"]]
    assert "".join(out) + stream.flush() == "It expired[1]. Also [2,3] and 【note】"
    assert out[1:3] == ["", ""]  # held back until the marker closed
    # A marker the answer ends in the middle of is not lost.
    stream = chat_service.CitationStream()
    assert stream.feed("cut off 【1") == "cut off "
    assert stream.flush() == "【1"


def test_prompt_numbers_passages_and_includes_history():
    history = [Message(role="user", content="Earlier question"), Message(role="assistant", content="Earlier answer [1]")]
    prompt = chat_service.build_prompt(history, "New question", SOURCES)
    assert prompt[0].role == "system"
    assert "[1] (Handbook, page 2)\nPassage 1 text." in prompt[0].content
    assert "[2] (Policy)\nPassage 2 text." in prompt[0].content
    assert [m.role for m in prompt[1:]] == ["user", "assistant", "user"]
    assert prompt[-1].content == "New question"


def test_prompt_says_when_nothing_matched():
    assert chat_service.NO_CONTEXT in chat_service.build_prompt([], "Q", [])[0].content


def test_provider_choice(env):
    _, session, user_id = env
    conversation = chat_service.create_conversation(session, user_id)

    with pytest.raises(chat_service.ProviderChoiceError, match="Add an API key"):
        chat_service.resolve_provider_choice(session, user_id, conversation, None, None)

    _add_key(session, user_id, "groq")
    assert chat_service.resolve_provider_choice(session, user_id, conversation, None, None) == ("groq", "openai/gpt-oss-120b")

    _add_key(session, user_id, "openai")
    with pytest.raises(chat_service.ProviderChoiceError, match="Choose a provider"):
        chat_service.resolve_provider_choice(session, user_id, conversation, None, None)
    assert chat_service.resolve_provider_choice(session, user_id, conversation, "openai", "gpt-4o") == ("openai", "gpt-4o")

    with pytest.raises(chat_service.ProviderChoiceError, match="Unknown provider"):
        chat_service.resolve_provider_choice(session, user_id, conversation, "acme", None)
    with pytest.raises(chat_service.ProviderChoiceError, match="no default model"):
        chat_service.resolve_provider_choice(session, user_id, conversation, "custom", None)


def test_turn_without_stored_key_is_refused_before_any_call(env):
    _, session, user_id = env
    conversation = chat_service.create_conversation(session, user_id)
    factory = FakeFactory()
    with pytest.raises(chat_service.ProviderChoiceError, match="No API key stored"):
        chat_service.prepare_turn(session, user_id, conversation.id, "Q", provider="openai", factory=factory, retriever=lambda *a, **k: [])
    assert factory.created == []


def test_full_turn_saves_answer_citations_and_telemetry(env):
    session_factory, session, user_id = env
    _add_key(session, user_id)
    conversation = chat_service.create_conversation(session, user_id)
    session.commit()
    provider = FakeProvider(reply="Leave is 25 days [1].", usage=Usage(200, 10))
    factory = FakeFactory(provider)

    turn = chat_service.prepare_turn(
        session, user_id, conversation.id, "How much leave?", factory=factory, retriever=lambda *a, **k: SOURCES,
    )
    session.commit()
    assert factory.created == [("openai", "sk-test-12345678", None)]

    events = []

    async def collect():
        async for event in chat_service.stream_turn(turn, session_factory):
            events.append(event)

    asyncio.run(collect())
    names = [name for name, _ in events]
    assert names[-2:] == ["citations", "done"]
    assert "".join(d["text"] for n, d in events if n == "token") == "Leave is 25 days [1]."
    done = events[-1][1]
    assert (done["prompt_tokens"], done["completion_tokens"]) == (200, 10)
    assert done["cost_usd"] == pytest.approx((200 * 0.15 + 10 * 0.60) / 1e6)
    assert done["ttft_ms"] is not None

    session.expire_all()
    messages = session.query(Message).filter(Message.conversation_id == conversation.id).order_by(Message.id).all()
    assert [(m.role, m.content) for m in messages] == [("user", "How much leave?"), ("assistant", "Leave is 25 days [1].")]
    assert [c["number"] for c in messages[1].citations] == [1]
    assert len(messages[1].context) == 2 and messages[1].context[1]["content"] == "Passage 2 text."
    event = session.query(TelemetryEvent).one()
    assert (event.operation, event.status, event.message_id) == ("chat", "ok", messages[1].id)

    # The conversation remembers the provider and gets a title from the first question.
    session.refresh(conversation)
    assert (conversation.provider, conversation.model, conversation.title) == ("openai", "gpt-4o-mini", "How much leave?")

    # The next turn sends the previous exchange as history.
    turn2 = chat_service.prepare_turn(session, user_id, conversation.id, "And sick days?", factory=factory, retriever=lambda *a, **k: [])
    assert [m.content for m in turn2.prompt[1:]] == ["How much leave?", "Leave is 25 days [1].", "And sick days?"]


class _DeltaProvider(FakeProvider):
    """Streams exactly the deltas given, as a real provider may split them."""

    def __init__(self, deltas: list[str], **kwargs):
        super().__init__(reply="".join(deltas), **kwargs)
        self.deltas = deltas

    async def stream(self, messages, model, max_tokens):
        for text in self.deltas:
            yield StreamEvent(kind="delta", text=text)
        yield StreamEvent(kind="done", usage=self.usage, model=model, finish_reason="stop")


def test_a_turn_streams_and_stores_full_width_citations_as_ordinary_ones(env):
    session_factory, session, user_id = env
    _add_key(session, user_id)
    conversation = chat_service.create_conversation(session, user_id)
    session.commit()
    factory = FakeFactory(_DeltaProvider(["Leave is 25 days", "【", "1", "】", "."]))
    turn = chat_service.prepare_turn(
        session, user_id, conversation.id, "How much leave?", factory=factory, retriever=lambda *a, **k: SOURCES,
    )
    session.commit()

    async def collect():
        return [event async for event in chat_service.stream_turn(turn, session_factory)]

    events = asyncio.run(collect())
    assert [d["text"] for n, d in events if n == "token"] == ["Leave is 25 days", "[1]", "."]
    assert [c["number"] for n, d in events if n == "citations" for c in d["citations"]] == [1]
    session.expire_all()
    stored = session.query(Message).filter(Message.role == "assistant").one()
    assert stored.content == "Leave is 25 days[1]."


def test_provider_failure_yields_error_event_and_records_it(env):
    session_factory, session, user_id = env
    _add_key(session, user_id)
    conversation = chat_service.create_conversation(session, user_id)
    factory = FakeFactory(FakeProvider(error=ProviderError("openai returned HTTP 429: slow down", status_code=429)))
    turn = chat_service.prepare_turn(session, user_id, conversation.id, "Q", factory=factory, retriever=lambda *a, **k: [])
    session.commit()

    with pytest.raises(chat_service.ChatProviderError, match="429"):
        asyncio.run(chat_service.run_turn(turn, session_factory))

    session.expire_all()
    assert session.query(TelemetryEvent).one().status == "error"
    assert [m.role for m in session.query(Message).all()] == ["user"]


def test_conversations_are_private(env):
    _, session, user_id = env
    conversation = chat_service.create_conversation(session, user_id, title="Mine")
    other = make_user(session)
    with pytest.raises(chat_service.ConversationNotFoundError):
        chat_service.get_conversation(session, other.id, conversation.id)
    with pytest.raises(chat_service.ConversationNotFoundError):
        chat_service.delete_conversation(session, other.id, conversation.id)
    assert chat_service.list_conversations(session, other.id) == []


def _msg(role, content):
    return Message(role=role, content=content)


def test_history_keeps_only_answered_questions_and_alternates():
    messages = [
        _msg("user", "q1"), _msg("assistant", "a1"),
        _msg("user", "q2 failed"),  # provider error: no answer stored
        _msg("user", "q3"), _msg("assistant", "a3"),
        _msg("user", "q4 interrupted"),
    ]
    history = chat_service.answered_history(messages, max_turns=6)
    assert [m.content for m in history] == ["q1", "a1", "q3", "a3"]
    assert [m.content for m in chat_service.answered_history(messages, max_turns=1)] == ["q3", "a3"]
    assert chat_service.answered_history(messages, max_turns=0) == []


def test_turn_after_a_failed_turn_sends_alternating_roles(env):
    session_factory, session, user_id = env
    _add_key(session, user_id)
    conversation = chat_service.create_conversation(session, user_id)
    failing = FakeFactory(FakeProvider(error=ProviderError("openai returned HTTP 429", status_code=429)))
    turn = chat_service.prepare_turn(session, user_id, conversation.id, "Q1", factory=failing, retriever=lambda *a, **k: [])
    session.commit()
    with pytest.raises(chat_service.ChatProviderError):
        asyncio.run(chat_service.run_turn(turn, session_factory))

    session.expire_all()
    turn2 = chat_service.prepare_turn(
        session, user_id, conversation.id, "Q2", factory=FakeFactory(FakeProvider(reply="ok")), retriever=lambda *a, **k: []
    )
    assert [(m.role, m.content) for m in turn2.prompt[1:]] == [("user", "Q2")]


def test_a_title_chosen_at_creation_is_kept(env):
    _, session, user_id = env
    _add_key(session, user_id)
    conversation = chat_service.create_conversation(session, user_id, title="Q3 contract review")
    chat_service.prepare_turn(
        session, user_id, conversation.id, "What is the termination clause?",
        factory=FakeFactory(FakeProvider(reply="x")), retriever=lambda *a, **k: [],
    )
    assert conversation.title == "Q3 contract review"


def test_each_turn_moves_the_conversation_to_the_top(env):
    session_factory, session, user_id = env
    _add_key(session, user_id)
    factory = FakeFactory(FakeProvider(reply="answer"))

    def ask(conversation_id, question):
        turn = chat_service.prepare_turn(session, user_id, conversation_id, question, factory=factory, retriever=lambda *a, **k: [])
        session.commit()
        asyncio.run(chat_service.run_turn(turn, session_factory))
        session.expire_all()

    older = chat_service.create_conversation(session, user_id)
    session.commit()
    ask(older.id, "first")
    newer = chat_service.create_conversation(session, user_id)
    session.commit()
    assert [c.id for c in chat_service.list_conversations(session, user_id)] == [newer.id, older.id]

    # Same provider, model and title as before: nothing about the conversation row changes but the time.
    ask(older.id, "second")
    assert [c.id for c in chat_service.list_conversations(session, user_id)] == [older.id, newer.id]


def test_a_library_prompt_replaces_the_built_in_one():
    sources = [chat_service.RetrievedChunk(1, 1, "hr", 2, "Leave is 25 days.", 0.5, 1, 1)]
    messages = chat_service.build_prompt([], "How much leave?", sources, "Be brief about: {question}\n{context}")
    assert messages[0].content.startswith("Be brief about: How much leave?\n[1] (hr, page 2)\nLeave is 25 days.")
    assert chat_service.build_prompt([], "Q", sources)[0].content.startswith("You are RAGForge")
