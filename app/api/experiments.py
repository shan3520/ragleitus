"""Experiments: compare prompts, models and retrieval strategies on your questions."""
import re
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_provider_factory
from app.db.database import get_db
from app.models.user import User
from app.services import experiment_service
from app.services.llm import ProviderFactory

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


class Case(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    reference_answer: str | None = Field(default=None, max_length=20_000)


class Variant(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    prompt_version_id: int | None = Field(default=None, description="A prompt-library version; null for the built-in prompt")
    provider: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=255, description="The provider's default model if left out")
    retrieval: Literal["hybrid", "dense", "keyword"] = "hybrid"
    top_k: int | None = Field(default=None, ge=1, le=experiment_service.MAX_TOP_K)


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    cases: list[Case] = Field(min_length=1, max_length=experiment_service.MAX_CASES)
    variants: list[Variant] = Field(min_length=1, max_length=experiment_service.MAX_VARIANTS)
    document_ids: list[int] | None = Field(default=None, max_length=1000, description="Only search these documents")
    evaluate: bool = Field(default=True, description="Score every answer with the LLM judge")
    judge_provider: str | None = Field(default=None, max_length=100, description="Defaults to each variant's own provider")
    judge_model: str | None = Field(default=None, max_length=255)
    evaluator: str = Field(default="builtin", description="builtin, ragas or deepeval (see GET /api/evaluators)")
    run: bool = Field(default=False, description="Start running it right away")


def _raise(exc: experiment_service.ExperimentError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("")
def list_experiments(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """Your experiments, newest first, with their progress."""
    return experiment_service.describe_all(session, user.id)


@router.get("/report")
def experiment_report(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """Every experiment with its best variant per metric, and the best variant of the latest finished one."""
    return experiment_service.report(session, user.id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_experiment(
    payload: ExperimentCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    factory: ProviderFactory = Depends(get_provider_factory),
):
    """Create an experiment: questions (with optional reference answers) and the variants to compare."""
    try:
        experiment = experiment_service.create_experiment(
            session, user.id, payload.name,
            [c.model_dump() for c in payload.cases], [v.model_dump() for v in payload.variants],
            payload.document_ids, payload.evaluate, payload.judge_provider, payload.judge_model, payload.evaluator,
        )
        if payload.run:
            experiment_service.start_run(session, user.id, experiment.id)
    except experiment_service.ExperimentError as exc:
        _raise(exc)
    session.commit()
    if payload.run:
        experiment_service.schedule_run(experiment.id, background_tasks, factory)
    return experiment_service.describe(session, experiment)


@router.get("/{experiment_id}")
def get_experiment(experiment_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    try:
        return experiment_service.describe(session, experiment_service.get_experiment(session, user.id, experiment_id))
    except experiment_service.ExperimentError as exc:
        _raise(exc)


@router.delete("/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_experiment(experiment_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    try:
        experiment_service.delete_experiment(session, user.id, experiment_id)
    except experiment_service.ExperimentError as exc:
        _raise(exc)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{experiment_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_experiment(
    experiment_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    factory: ProviderFactory = Depends(get_provider_factory),
):
    """Run (or re-run) the experiment; earlier results are replaced."""
    try:
        experiment = experiment_service.start_run(session, user.id, experiment_id)
    except experiment_service.ExperimentError as exc:
        _raise(exc)
    session.commit()
    experiment_service.schedule_run(experiment.id, background_tasks, factory)
    return experiment_service.describe(session, experiment)


@router.get("/{experiment_id}/compare")
def compare_experiment(experiment_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """Per-variant averages (judge scores, ROUGE-L, latency, cost), the best variant per metric, and every answer."""
    try:
        return experiment_service.compare(session, user.id, experiment_id)
    except experiment_service.ExperimentError as exc:
        _raise(exc)


def _filename(name: str, extension: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:80] or "experiment"
    return f"{slug}.{extension}"


@router.get("/{experiment_id}/export")
def export_experiment(
    experiment_id: int,
    format: Literal["csv", "json"] = Query("csv"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Every result, one row per question and variant, as CSV or JSON."""
    try:
        if format == "csv":
            experiment, body = experiment_service.export_csv(session, user.id, experiment_id)
            return Response(
                body, media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{_filename(experiment.name, "csv")}"'},
            )
        experiment, data = experiment_service.export_json(session, user.id, experiment_id)
        return JSONResponse(
            jsonable_encoder(data),
            headers={"Content-Disposition": f'attachment; filename="{_filename(experiment.name, "json")}"'},
        )
    except experiment_service.ExperimentError as exc:
        _raise(exc)
