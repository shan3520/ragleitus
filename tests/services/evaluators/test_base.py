import asyncio

import pytest
from pydantic import BaseModel

from app.services.evaluators.base import JudgeError, JudgeModel, Scores, clean_score, extract_json
from app.services.llm import ChatMessage, ProviderError
from tests.fakes import FakeProvider, SchemaJudgeProvider


class Verdict(BaseModel):
    statement: str
    verdict: int


def test_complete_logs_each_call_and_turns_provider_errors_into_judge_errors():
    judge = JudgeModel("openai", FakeProvider(reply="hello"), "gpt-4o-mini")
    assert asyncio.run(judge.complete([ChatMessage("user", "hi")])) == "hello"
    assert judge.calls[0].completion_text == "hello" and judge.calls[0].usage.prompt_tokens == 100

    failing = JudgeModel("openai", FakeProvider(error=ProviderError("OpenAI returned HTTP 429: slow down", 429)), "m")
    with pytest.raises(JudgeError, match="429"):
        asyncio.run(failing.complete([ChatMessage("user", "hi")]))
    assert failing.calls[0].error is not None


def test_complete_json_fills_the_schema_and_retries_unreadable_replies():
    provider = SchemaJudgeProvider(bad_replies=2)
    judge = JudgeModel("openai", provider, "m")
    result = asyncio.run(judge.complete_json("Judge this.", Verdict))
    assert result == Verdict(statement="A statement.", verdict=1)
    assert len(judge.calls) == 3
    # The retry shows the model its reply and what was wrong with it.
    assert provider.calls[-1]["messages"][-1].content.startswith("That was not valid JSON")

    hopeless = JudgeModel("openai", SchemaJudgeProvider(bad_replies=5), "m")
    with pytest.raises(JudgeError, match="did not return the expected JSON"):
        asyncio.run(hopeless.complete_json("Judge this.", Verdict))


def test_scores_are_clamped_and_nan_is_missing():
    assert clean_score(1.7) == 1.0 and clean_score(-1) == 0.0 and clean_score(0.12345) == 0.1235
    assert clean_score(float("nan")) is None and clean_score(None) is None and clean_score("x") is None
    assert Scores(0.75, 1, 1, None).hallucination_score() == 0.25
    assert Scores(None, 1, 1, None).hallucination_score() is None
    assert Scores(0.75, 1, 1, None, hallucination=0.1).hallucination_score() == 0.1
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    with pytest.raises(ValueError):
        extract_json("no json")
