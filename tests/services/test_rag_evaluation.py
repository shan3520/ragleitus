import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.conversation import Conversation, Message
from app.models.telemetry_event import TelemetryEvent
from app.services import rag_evaluation
from app.services.llm import ProviderError
from app.services.provider_key import encrypt_key, save_provider_key
from tests.fakes import FakeFactory, FakeProvider
from tests.helpers import make_user

JUDGE_JSON = '{"faithfulness": 0.9, "answer_relevancy": 1.0, "context_precision": 0.5, "context_recall": 0.8, "rationale": "Mostly supported."}'


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'eval.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = make_user(session)
    save_provider_key(session, user.id, "openai", encrypt_key("sk-test-12345678"))
    conversation = Conversation(user_id=user.id, title="t")
    session.add(conversation)
    session.flush()
    question = Message(conversation_id=conversation.id, role="user", content="How much leave?")
    answer = Message(
        conversation_id=conversation.id, role="assistant", content="Employees get 25 days of leave [1].",
        provider="openai", model="gpt-4o-mini",
        context=[{"number": 1, "content": "Employees get 25 days of annual leave."},
                 {"number": 2, "content": "The cafeteria opens at 8."}],
    )
    session.add_all([question, answer])
    session.commit()
    yield session, user.id, question, answer
    session.close()


def test_parse_judge_output_handles_fences_and_clamps():
    scores = rag_evaluation.parse_judge_output("```json\n" + JUDGE_JSON.replace("1.0", "1.7") + "\n```", has_reference=True)
    assert scores.answer_relevancy == 1.0
    assert scores.context_recall == 0.8
    assert rag_evaluation.parse_judge_output(JUDGE_JSON, has_reference=False).context_recall is None


@pytest.mark.parametrize("bad", ["no json here", '{"faithfulness": "high"}', '{"answer_relevancy": 1}'])
def test_parse_judge_output_rejects_garbage(bad):
    with pytest.raises(rag_evaluation.JudgeError):
        rag_evaluation.parse_judge_output(bad, has_reference=False)


def test_judge_prompt_contains_everything_the_judge_needs():
    prompt = rag_evaluation.build_judge_prompt("Q?", [{"number": 1, "content": "P1"}], "A", "Ref")
    body = prompt[1].content
    assert "QUESTION:\nQ?" in body and "[1] P1" in body and "ANSWER:\nA" in body and "REFERENCE ANSWER:\nRef" in body
    assert "REFERENCE ANSWER" not in rag_evaluation.build_judge_prompt("Q?", [], "A", None)[1].content


def test_evaluate_message_stores_scores_baselines_and_telemetry(env):
    session, user_id, _, answer = env
    factory = FakeFactory(FakeProvider(reply=JUDGE_JSON))
    evaluation = asyncio.run(rag_evaluation.evaluate_message(
        session, user_id, answer.id, reference="Staff receive 25 days of leave.", factory=factory,
    ))
    assert (evaluation.judge_provider, evaluation.judge_model) == ("openai", "gpt-4o-mini")
    assert evaluation.faithfulness == 0.9
    assert evaluation.hallucination == pytest.approx(0.1)
    assert evaluation.context_recall == 0.8
    assert evaluation.rouge_l is not None and evaluation.context_overlap is not None
    judge_input = factory.provider.calls[0]["messages"][1].content
    assert "How much leave?" in judge_input and "The cafeteria opens at 8." in judge_input
    event = session.query(TelemetryEvent).one()
    assert (event.operation, event.message_id) == ("evaluation", answer.id)


def test_evaluate_rejects_user_messages_foreign_messages_and_missing_keys(env):
    session, user_id, question, answer = env
    factory = FakeFactory(FakeProvider(reply=JUDGE_JSON))
    with pytest.raises(rag_evaluation.EvaluationError, match="Only assistant"):
        asyncio.run(rag_evaluation.evaluate_message(session, user_id, question.id, factory=factory))
    other = make_user(session)
    with pytest.raises(rag_evaluation.MessageNotFoundError):
        asyncio.run(rag_evaluation.evaluate_message(session, other.id, answer.id, factory=factory))
    with pytest.raises(rag_evaluation.ProviderChoiceError, match="No API key"):
        asyncio.run(rag_evaluation.evaluate_message(session, user_id, answer.id, provider="anthropic", factory=factory))


def test_judge_failure_is_reported_and_recorded(env):
    session, user_id, _, answer = env
    factory = FakeFactory(FakeProvider(error=ProviderError("HTTP 500", status_code=500)))
    with pytest.raises(rag_evaluation.JudgeError):
        asyncio.run(rag_evaluation.evaluate_message(session, user_id, answer.id, factory=factory))
    assert session.query(TelemetryEvent).one().status == "error"


def test_list_evaluations_with_averages(env):
    session, user_id, _, answer = env
    for reply in (JUDGE_JSON, JUDGE_JSON.replace('"faithfulness": 0.9', '"faithfulness": 0.5')):
        asyncio.run(rag_evaluation.evaluate_message(session, user_id, answer.id, factory=FakeFactory(FakeProvider(reply=reply))))
    items, total, averages = rag_evaluation.list_evaluations(session, user_id)
    assert total == 2
    assert averages["faithfulness"] == pytest.approx(0.7)
    assert averages["context_recall"] is None
    assert items[0].faithfulness == 0.5
    assert rag_evaluation.list_evaluations(session, make_user(session).id)[1] == 0


def test_history_gives_conversation_ids_without_loading_answer_text(env):
    from sqlalchemy import inspect

    from app.models.answer_evaluation import AnswerEvaluation

    session, user_id, _, answer = env
    session.add(AnswerEvaluation(
        user_id=user_id, message_id=answer.id, judge_provider="openai", judge_model="m",
        faithfulness=1, answer_relevancy=1, context_precision=1, hallucination=0,
    ))
    session.commit()
    conversation_id = answer.conversation_id
    session.expunge_all()

    items, _, _ = rag_evaluation.list_evaluations(session, user_id)
    assert items[0].conversation_id == conversation_id
    unloaded = inspect(items[0].message).unloaded
    assert {"content", "context"} <= unloaded
