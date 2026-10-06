import asyncio
import csv
import io
import threading
from datetime import timedelta
from functools import partial

import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models import Base
from app.models.experiment import Experiment, ExperimentResult
from app.models.telemetry_event import TelemetryEvent
from app.services import experiment_runner, experiment_service, ingestion, prompt_service
from app.services.embeddings import FakeEmbedder
from app.services.llm import ProviderError, StreamEvent
from app.services.experiment_service import ExperimentBusyError, ExperimentError
from app.services.provider_key import encrypt_key, save_provider_key
from app.services.retrieval import retrieve
from app.services.vector_store import VectorStore
from tests.fakes import FakeFactory, ScriptedProvider
from tests.helpers import make_user

CASES = [
    {"question": "What does error E-4711 mean?", "reference_answer": "The upstream certificate expired."},
    {"question": "How many days of annual leave?"},
]


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'experiments.db'}")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    yield from _env(engine)


@pytest.fixture
def pg_env():
    """The same, on PostgreSQL (TEST_POSTGRES_URL), where runs really write concurrently."""
    from tests.postgres import POSTGRES_URL, fresh_postgres

    if not POSTGRES_URL:
        pytest.skip("TEST_POSTGRES_URL is not set")
    engine = fresh_postgres()
    yield from _env(engine)
    engine.dispose()


def _env(engine):
    factory = sessionmaker(bind=engine)
    embedder = FakeEmbedder()
    store = VectorStore(QdrantClient(location=":memory:"), embedder.model_name, embedder.dimension)
    session = factory()
    user = make_user(session)
    for provider in ("openai", "mistral"):
        save_provider_key(session, user.id, provider, encrypt_key("sk-experimentkey1234"))
    session.commit()
    for name, text in [
        ("errors.txt", "Error E-4711 means the upstream certificate expired."),
        ("hr.txt", "Employees receive 25 days of annual leave."),
    ]:
        doc = ingestion.create_document(session, user.id, name, text.encode())
        session.commit()
        ingestion.index_document(doc.id, session_factory=factory, embedder=embedder, store=store)
    session.expire_all()

    def run(experiment_id, provider=None, retriever=None):
        provider = provider or ScriptedProvider()
        experiment_runner.run_experiment(
            experiment_id, session_factory=factory, factory=FakeFactory(provider),
            retriever=retriever or partial(retrieve, embedder=embedder, store=store),
        )
        session.expire_all()
        return provider

    yield session, user, run
    session.close()


def _create(session, user, **overrides):
    prompt = prompt_service.create_prompt(session, user.id, "Brief", "Be brief.\n\n[context]\n{context}")
    params = dict(
        name="Prompts vs retrieval",
        cases=CASES,
        variants=[
            {"label": "Built-in", "provider": "openai", "model": "gpt-4o-mini"},
            {"label": "Brief + keyword", "provider": "openai", "prompt_version_id": prompt.versions[0].id,
             "retrieval": "keyword", "top_k": 2},
        ],
    )
    params.update(overrides)
    experiment = experiment_service.create_experiment(session, user.id, **params)
    experiment_service.start_run(session, user.id, experiment.id)
    session.commit()
    return experiment


def test_a_run_answers_every_question_with_every_variant_and_scores_it(env):
    session, user, run = env
    experiment = _create(session, user)

    provider = run(experiment.id)

    experiment = session.get(Experiment, experiment.id)
    assert experiment.status == "completed" and experiment.finished_at is not None
    results = session.query(ExperimentResult).order_by(ExperimentResult.case_index, ExperimentResult.variant_id).all()
    assert len(results) == 4
    first = results[0]
    assert first.answer.startswith("Answer: Error E-4711 means") and first.answer.endswith("[1]")
    assert first.citations[0]["document_title"] == "errors"
    assert first.context[0]["content"].startswith("Error E-4711")
    assert (first.faithfulness, first.answer_relevancy, first.context_precision) == (0.9, 0.8, 0.5)
    assert first.context_recall == 0.6 and first.hallucination == pytest.approx(0.1)
    assert first.rouge_l is not None  # a reference answer was given
    assert first.cost_usd is not None and first.prompt_tokens == 100
    assert results[2].context_recall is None and results[2].rouge_l is None  # no reference for question 2
    assert all(r.error is None for r in results)

    # The second variant answered with the library prompt; the first with the built-in one.
    answers = [c for c in provider.calls if "impartial evaluator" not in c["messages"][0].content]
    assert len(answers) == 4
    assert sum(c["messages"][0].content.startswith("Be brief.") for c in answers) == 2
    # Every call is in telemetry.
    operations = sorted(op for (op,) in session.query(TelemetryEvent.operation))
    assert operations == ["evaluation"] * 4 + ["experiment"] * 4


class _FullWidthCiter(ScriptedProvider):
    """Cites 【1】 instead of [1], as gpt-oss-120b on Groq does."""

    async def stream(self, messages, model, max_tokens):
        async for event in super().stream(messages, model, max_tokens):
            if event.kind == "delta":
                event = StreamEvent(kind="delta", text=event.text.replace("[1]", "【1】"))
            yield event


def test_full_width_citations_are_stored_as_ordinary_ones(env):
    session, user, run = env
    experiment = _create(session, user)

    run(experiment.id, provider=_FullWidthCiter())

    first = session.query(ExperimentResult).order_by(ExperimentResult.case_index, ExperimentResult.variant_id).first()
    assert first.answer.endswith("expired. [1]"), first.answer
    assert first.citations[0]["document_title"] == "errors"


def test_compare_export_and_report(env):
    session, user, run = env
    experiment = _create(session, user)
    run(experiment.id)

    comparison = experiment_service.compare(session, user.id, experiment.id)
    built_in, brief = comparison["variants"]
    assert (built_in["label"], built_in["results"], built_in["errors"]) == ("Built-in", 2, 0)
    assert brief["prompt_label"] == "Brief v1" and brief["retrieval"] == "keyword"
    assert built_in["averages"]["faithfulness"] == 0.9
    assert built_in["averages"]["quality"] is not None
    assert built_in["total_cost_usd"] > 0
    assert comparison["experiment"]["progress"] == {"done": 4, "total": 4}
    assert [c["question"] for c in comparison["cases"]] == [c["question"] for c in CASES]
    assert set(comparison["cases"][0]["results"]) == {built_in["id"], brief["id"]}

    _, text = experiment_service.export_csv(session, user.id, experiment.id)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 4
    assert rows[0]["variant"] == "Built-in" and rows[0]["question"] == CASES[0]["question"]
    assert rows[0]["cited_passages"] == "[1]"
    _, data = experiment_service.export_json(session, user.id, experiment.id)
    assert len(data["results"]) == 4 and data["experiment"]["name"] == "Prompts vs retrieval"

    # The fake judge scores every answer alike: no variant is ahead.
    assert "faithfulness" not in comparison["best"] and "quality" not in comparison["best"]
    report = experiment_service.report(session, user.id)
    assert report["experiments_evaluated"] == 1
    assert report["best_performing"] is None
    assert report["experiments"][0]["status"] == "completed"
    assert experiment_service.report(session, make_user(session).id)["experiments"] == []


def test_the_best_variant_is_the_one_strictly_ahead(env):
    session, user, run = env
    experiment = _create(session, user)
    run(experiment.id)
    built_in_id, brief_id = [v.id for v in experiment.variants]
    # The library-prompt variant's answers were judged less faithful.
    session.query(ExperimentResult).filter(ExperimentResult.variant_id == brief_id).update({ExperimentResult.faithfulness: 0.4})
    session.commit()

    comparison = experiment_service.compare(session, user.id, experiment.id)
    assert comparison["best"]["faithfulness"] == built_in_id
    assert comparison["best"]["quality"] == built_in_id
    assert "answer_relevancy" not in comparison["best"]  # a tie
    assert experiment_service.report(session, user.id)["best_performing"]["variant"] == "Built-in"


def test_exported_cells_cannot_run_as_spreadsheet_formulas(env):
    session, user, run = env
    experiment = _create(session, user, cases=[{"question": "=HYPERLINK(\"http://evil\")"}])
    run(experiment.id)
    _, text = experiment_service.export_csv(session, user.id, experiment.id)
    assert "'=HYPERLINK" in text


def test_a_failing_variant_or_judge_does_not_stop_the_run(env):
    session, user, run = env
    experiment = _create(session, user)

    # The library-prompt variant's calls fail; the judge returns no JSON.
    provider = ScriptedProvider(
        fail_when=lambda messages: messages[0].content.startswith("Be brief."),
        judge_reply="I refuse to output JSON.",
    )
    run(experiment.id, provider=provider)

    assert session.get(Experiment, experiment.id).status == "completed"
    results = session.query(ExperimentResult).order_by(ExperimentResult.case_index, ExperimentResult.variant_id).all()
    built_in, brief = results[0], results[1]
    assert brief.answer is None and brief.error == "Fake provider is down" and brief.cost_usd is None
    assert built_in.answer and built_in.error.startswith("Evaluation failed: The judge model did not return JSON")
    assert built_in.faithfulness is None and built_in.rouge_l is not None
    comparison = experiment_service.compare(session, user.id, experiment.id)
    assert [v["errors"] for v in comparison["variants"]] == [2, 2]
    failed = session.query(TelemetryEvent).filter(TelemetryEvent.status == "error").count()
    assert failed == 2


def test_without_evaluation_only_the_lexical_score_is_kept(env):
    session, user, run = env
    experiment = _create(session, user, evaluate=False)
    provider = run(experiment.id)
    assert not any("impartial evaluator" in c["messages"][0].content for c in provider.calls)
    first = session.query(ExperimentResult).order_by(ExperimentResult.case_index, ExperimentResult.variant_id).first()
    assert first.faithfulness is None and first.rouge_l is not None


def test_a_run_that_was_replaced_stops_and_a_duplicate_job_does_nothing(env):
    session, user, run = env
    experiment = _create(session, user)
    other_session = sessionmaker(bind=session.get_bind())()

    def retriever_that_restarts_the_run(*args, **kwargs):
        # The user deletes the run's results and starts again while it is going.
        other_session.query(Experiment).filter(Experiment.id == experiment.id).update({Experiment.run_token: "newer"})
        other_session.commit()
        return []

    run(experiment.id, retriever=retriever_that_restarts_the_run)
    assert session.query(ExperimentResult).count() == 0
    assert session.get(Experiment, experiment.id).status == "running"  # the newer run's to finish

    session.get(Experiment, experiment.id).status = "completed"
    session.commit()
    provider = run(experiment.id)  # not queued: nothing happens
    assert provider.calls == []
    other_session.close()


def test_retrieval_strategies_are_passed_through(env):
    session, user, run = env
    experiment = _create(session, user)
    seen = []

    def recording_retriever(session_, user_id, question, **kwargs):
        seen.append((kwargs["strategy"], kwargs["k"], kwargs["document_ids"], kwargs["rerank"]))
        return []

    run(experiment.id, retriever=recording_retriever)
    assert sorted(set(seen)) == [("hybrid", settings.retrieval_top_k, None, False), ("keyword", 2, None, False)]


def test_a_variant_can_rerank_and_is_checked_again_before_a_run(env):
    from app.services import reranking

    session, user, run = env
    reranking.save_choice(session, user.id, "local", None)
    session.commit()
    experiment = _create(session, user, variants=[
        {"label": "Fused", "provider": "openai"},
        {"label": "Reranked", "provider": "openai", "rerank": True},
    ])
    seen = []

    def recording_retriever(session_, user_id, question, **kwargs):
        seen.append(kwargs["rerank"])
        return []

    run(experiment.id, retriever=recording_retriever)
    assert sorted(set(seen)) == [False, True]
    described = experiment_service.describe(session, session.get(Experiment, experiment.id))
    assert [v["rerank"] for v in described["variants"]] == [False, True]
    _, rows = experiment_service.export_rows(session, user.id, experiment.id)
    assert {row["variant"]: row["reranked"] for row in rows} == {"Fused": False, "Reranked": True}

    # Reranking turned off since: the variant can't run as labelled.
    reranking.save_choice(session, user.id, "none", None)
    session.commit()
    with pytest.raises(ExperimentError, match="Reranked: turn on reranking in Settings first"):
        experiment_service.start_run(session, user.id, experiment.id)


# ---------------------------------------------------------------- create and run


def test_variants_and_questions_are_checked(env):
    session, user, _ = env
    other = make_user(session)
    foreign = prompt_service.create_prompt(session, other.id, "Theirs", "{context}")
    base = {"label": "A", "provider": "openai"}

    def create(**kwargs):
        params = {"name": "x", "cases": CASES, "variants": [base]}
        params.update(kwargs)
        return experiment_service.create_experiment(session, user.id, **params)

    for kwargs, message in [
        ({"name": " "}, "name"),
        ({"cases": []}, "at least one question"),
        ({"cases": [{"question": " "}]}, "Question 1 is empty"),
        ({"variants": []}, "at least one variant"),
        ({"variants": [base] * 7}, "at most 6"),
        ({"variants": [{"provider": "groq"}]}, "no API key stored for Groq"),
        ({"variants": [{"provider": "nope"}]}, "unknown provider"),
        ({"variants": [{**base, "retrieval": "magic"}]}, "retrieval must be"),
        ({"variants": [{**base, "top_k": 50}]}, "top_k"),
        ({"variants": [base, base]}, "different label"),
        ({"variants": [{**base, "prompt_version_id": foreign.versions[0].id}]}, "prompt version not found"),
        ({"document_ids": [987654]}, "documents were not found"),
        ({"judge_provider": "anthropic"}, "Judge: no API key"),
        ({"variants": [{**base, "rerank": True}]}, "turn on reranking in Settings first"),
        ({"concurrency": 0}, "Concurrency must be between 1 and 16"),
        ({"concurrency": 17}, "Concurrency must be between 1 and 16"),
    ]:
        with pytest.raises(ExperimentError, match=message):
            create(**kwargs)

    experiment = create(variants=[{"provider": "mistral"}, {"provider": "openai", "model": "gpt-4o"}])
    assert [(v.label, v.model, v.prompt_label) for v in experiment.variants] == [
        ("Variant A", "mistral-small-latest", "Built-in prompt"), ("Variant B", "gpt-4o", "Built-in prompt"),
    ]
    assert experiment.status == "draft"
    assert experiment.concurrency == settings.experiment_concurrency  # the default


def test_a_running_experiment_cannot_be_started_twice_unless_its_run_was_lost(env):
    session, user, _ = env
    experiment = _create(session, user)
    assert experiment.status == "queued"
    with pytest.raises(ExperimentBusyError):
        experiment_service.start_run(session, user.id, experiment.id)

    experiment.started_at = experiment.started_at - timedelta(days=1)
    session.commit()
    assert experiment_service.is_stale(experiment)
    experiment_service.start_run(session, user.id, experiment.id)
    assert experiment.status == "queued"


def test_experiments_are_private(env):
    session, user, _ = env
    experiment = _create(session, user)
    stranger = make_user(session)
    for call in (
        lambda: experiment_service.get_experiment(session, stranger.id, experiment.id),
        lambda: experiment_service.compare(session, stranger.id, experiment.id),
        lambda: experiment_service.export_csv(session, stranger.id, experiment.id),
        lambda: experiment_service.start_run(session, stranger.id, experiment.id),
        lambda: experiment_service.delete_experiment(session, stranger.id, experiment.id),
    ):
        with pytest.raises(experiment_service.ExperimentNotFoundError):
            call()
    assert experiment_service.describe_all(session, stranger.id) == []


def test_a_deleted_prompt_or_a_judge_without_a_model_is_refused(env):
    session, user, run = env
    experiment = _create(session, user)
    run(experiment.id)
    brief = next(v for v in experiment.variants if v.prompt_version_id)
    prompt_service.delete_prompt(session, user.id, brief.prompt_version.prompt_id)
    session.commit()
    session.expire_all()

    with pytest.raises(ExperimentError, match=r"its prompt \(Brief v1\) has been deleted"):
        experiment_service.start_run(session, user.id, experiment.id)
    # The results it produced are still labelled with the prompt they used.
    assert experiment_service.compare(session, user.id, experiment.id)["variants"][1]["prompt_label"] == "Brief v1"

    save_provider_key(session, user.id, "custom", encrypt_key("none"), "https://llm.example.com/v1")
    session.commit()
    with pytest.raises(ExperimentError, match="Judge: choose a model for OpenAI-compatible"):
        experiment_service.create_experiment(
            session, user.id, "x", CASES, [{"provider": "openai"}], judge_provider="custom"
        )


def test_a_run_that_cannot_be_queued_fails_so_it_can_be_retried(env, monkeypatch):
    session, user, _ = env
    experiment = _create(session, user)
    from app.services import experiment_service as service
    import app.worker as worker

    def broker_down(*args, **kwargs):
        raise ConnectionError("Redis is down")

    monkeypatch.setattr(service.settings, "task_queue", "celery")
    monkeypatch.setattr(worker.run_experiment_task, "delay", broker_down)
    monkeypatch.setattr("app.db.database.SessionLocal", sessionmaker(bind=session.get_bind()))
    service.schedule_run(experiment.id)

    session.expire_all()
    failed = session.get(Experiment, experiment.id)
    assert (failed.status, failed.error) == ("failed", "Could not queue the run; try again.")
    experiment_service.start_run(session, user.id, experiment.id)  # not busy


def test_an_experiment_can_be_scored_by_another_evaluator(env):
    from app.services import evaluators
    from tests.fakes import SchemaJudgeProvider

    if not evaluators.ragas_evaluator.installed():
        pytest.skip("ragas is not installed")
    session, user, run = env
    experiment = _create(session, user, evaluator="ragas")
    run(experiment.id, provider=SchemaJudgeProvider(prefix="Answer:"))
    results = session.query(ExperimentResult).all()
    assert len(results) == 4 and all(r.error is None for r in results)
    assert all(r.faithfulness == 1.0 for r in results)
    assert experiment_service.describe(session, session.get(Experiment, experiment.id))["evaluator"] == "ragas"
    with pytest.raises(ExperimentError, match="Unknown evaluator"):
        experiment_service.create_experiment(session, user.id, "x", CASES, [{"provider": "openai"}], evaluator="magic")


class _CountingProvider(ScriptedProvider):
    """Records how many calls were in flight at once (each takes a moment)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._lock = threading.Lock()
        self.in_flight = 0
        self.most_in_flight = 0

    async def stream(self, messages, model, max_tokens):
        with self._lock:
            self.in_flight += 1
            self.most_in_flight = max(self.most_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.05)
            async for event in super().stream(messages, model, max_tokens):
                yield event
        finally:
            with self._lock:
                self.in_flight -= 1


@pytest.mark.parametrize("database", ["env", "pg_env"])
@pytest.mark.parametrize("concurrency", [1, 4])
def test_answers_are_worked_on_concurrently_and_each_stored_once(request, database, concurrency):
    session, user, run = request.getfixturevalue(database)
    cases = [{"question": f"What does error E-4711 mean? ({i})"} for i in range(5)]
    experiment = _create(session, user, cases=cases, concurrency=concurrency)

    provider = run(experiment.id, provider=_CountingProvider())

    assert session.get(Experiment, experiment.id).status == "completed"
    stored = sorted((r.case_index, r.variant_id) for r in session.query(ExperimentResult))
    expected = sorted((i, v.id) for i in range(5) for v in session.get(Experiment, experiment.id).variants)
    assert stored == expected  # every question x variant, once
    assert all(r.error is None and r.answer for r in session.query(ExperimentResult))
    assert provider.most_in_flight == 1 if concurrency == 1 else provider.most_in_flight > 1
    assert session.query(TelemetryEvent).count() == 20  # 10 answers + 10 judgements


def test_rate_limited_calls_are_retried(env):
    session, user, run = env
    experiment = _create(session, user, concurrency=1)  # one at a time: every other call is limited

    class RateLimited(ScriptedProvider):
        async def stream(self, messages, model, max_tokens):
            if len(self.calls) % 2 == 0:
                self.calls.append({"messages": messages, "model": model, "max_tokens": max_tokens})
                raise ProviderError("openai returned HTTP 429: slow down", 429, retry_after=0.01)
            async for event in super().stream(messages, model, max_tokens):
                yield event

    provider = run(experiment.id, provider=RateLimited())

    results = session.query(ExperimentResult).all()
    assert len(results) == 4 and all(r.error is None and r.faithfulness is not None for r in results)
    assert len(provider.calls) == 16  # 4 answers and 4 judgements, each rate limited once first
    assert session.query(TelemetryEvent).filter(TelemetryEvent.status == "error").count() == 0


@pytest.mark.parametrize("database", ["env", "pg_env"])
def test_a_run_replaced_while_running_concurrently_stops_the_rest(request, database):
    session, user, run = request.getfixturevalue(database)
    cases = [{"question": f"Question {i}"} for i in range(12)]
    experiment = _create(session, user, cases=cases, concurrency=3, evaluate=False)
    other_session = sessionmaker(bind=session.get_bind())()
    calls = []
    lock = threading.Lock()

    def retriever(*args, **kwargs):
        with lock:
            calls.append(1)
            if len(calls) == 3:
                other_session.query(Experiment).filter(Experiment.id == experiment.id).update(
                    {Experiment.run_token: "newer"}
                )
                other_session.commit()
        return []

    run(experiment.id, retriever=retriever)
    other_session.close()

    # Results finished before the takeover may be kept; nothing after it, and far from all 24.
    assert session.query(ExperimentResult).count() <= 2
    assert len(calls) < 24
    assert session.get(Experiment, experiment.id).status == "running"  # the newer run's


def test_a_reranker_that_fails_in_an_experiment_is_noted_on_the_result(env, monkeypatch):
    from app.services import reranking
    from app.services.rerankers import FakeReranker

    session, user, run = env
    reranking.save_choice(session, user.id, "local", None)
    session.commit()
    experiment = _create(session, user, evaluate=False, variants=[{"label": "Reranked", "provider": "openai", "rerank": True}])

    class Throttled(FakeReranker):
        calls_made = 0

        def rerank(self, query, passages):
            type(self).calls_made += 1
            if type(self).calls_made == 1:  # the first call is rate limited, then it works
                raise ProviderError("Together AI returned HTTP 429: slow down", 429)
            if "annual leave" in query:
                raise ProviderError("Together AI returned HTTP 400: passage too long", 400)
            return super().rerank(query, passages)

    monkeypatch.setattr(reranking, "build_reranker", lambda s, u, c: Throttled())
    run(experiment.id)

    results = {r.case_index: r for r in session.query(ExperimentResult)}
    assert results[0].error is None and results[0].answer  # retried after the 429
    assert results[1].answer  # still answered, with the passages in their fused order...
    assert results[1].error.startswith("Passages could not be reranked")  # ...and says so
    assert "HTTP 400: passage too long" in results[1].error
