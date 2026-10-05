import pytest

from app.services import evaluators
from app.services.evaluators import EvaluationError, EvaluatorUnavailable


def test_lists_every_evaluator_and_whether_it_can_run():
    listed = {e["name"]: e for e in evaluators.available()}
    assert list(listed) == ["builtin", "ragas", "deepeval"]
    assert listed["builtin"]["available"] is True
    assert all(e["label"] and e["description"] for e in listed.values())


def test_get_refuses_unknown_and_uninstalled_evaluators(monkeypatch):
    assert evaluators.get(None).NAME == "builtin"
    with pytest.raises(EvaluationError, match="Unknown evaluator 'magic'"):
        evaluators.get("magic")
    monkeypatch.setattr(evaluators.ragas_evaluator, "installed", lambda: False)
    with pytest.raises(EvaluatorUnavailable, match=r'Ragas is not installed on this server \(pip install "\.\[ragas\]"\)'):
        evaluators.get("ragas")
    assert {e["name"]: e["available"] for e in evaluators.available()}["ragas"] is False
