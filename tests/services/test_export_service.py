from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.answer_evaluation import AnswerEvaluation
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.services import export_service, telemetry
from app.services.llm import Usage
from tests.helpers import make_user


def test_export_gathers_usage_evaluations_and_activity_for_the_user_only():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    alice, bob = make_user(session), make_user(session)
    for user in (alice, bob):
        telemetry.record_llm_call(
            session, user_id=user.id, operation="chat", provider="openai", model="gpt-4o-mini",
            latency_ms=800, usage=Usage(1000, 200),
        )
    conversation = Conversation(user_id=alice.id, title="t")
    session.add(conversation)
    session.flush()
    session.add(Message(conversation_id=conversation.id, role="user", content="Q"))
    answer = Message(conversation_id=conversation.id, role="assistant", content="A")
    session.add(answer)
    session.flush()
    session.add(AnswerEvaluation(
        user_id=alice.id, message_id=answer.id, evaluator="ragas", judge_provider="openai", judge_model="gpt-4o-mini",
        faithfulness=0.9, answer_relevancy=0.8, context_precision=None, hallucination=0.1,
    ))
    session.add_all([Document(user_id=alice.id, title="a", status="ready"), Document(user_id=alice.id, title="b", status="failed")])
    session.commit()

    data = export_service.metrics_export(session, alice.id, "alice", days=7)

    assert data["user"] == "alice" and data["days"] == 7
    assert data["usage"]["totals"]["requests"] == 1
    assert data["usage"]["totals"]["prompt_tokens"] == 1000
    assert data["usage"]["by_model"][0]["model"] == "gpt-4o-mini"
    assert data["evaluations"] == {
        "count": 1, "by_evaluator": {"ragas": 1},
        "averages": {"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": None, "context_recall": None, "hallucination": 0.1},
    }
    assert data["activity"]["documents"] == {"pending": 0, "indexing": 0, "ready": 1, "failed": 1}
    assert data["activity"]["conversations"] == 1 and data["activity"]["questions"] == 1

    rows = export_service.metrics_rows(data)
    assert {"section": "usage", "key": "all", "metric": "requests", "value": 1} in rows
    assert {"section": "usage_by_model", "key": "openai/gpt-4o-mini", "metric": "prompt_tokens", "value": 1000} in rows
    assert {"section": "evaluations", "key": "ragas", "metric": "count", "value": 1} in rows
    assert {"section": "documents", "key": "failed", "metric": "count", "value": 1} in rows

    assert export_service.metrics_export(session, bob.id, "bob")["activity"]["conversations"] == 0
