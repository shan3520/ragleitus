from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_provider_factory
from app.models.user import User
from app.db.database import get_db
from app.services import evaluators, experiment_service, rag_evaluation
from app.services.chat_service import ChatError
from app.services.llm import ProviderFactory

router = APIRouter(tags=["evaluations"])


@router.get("/api/evaluations/summary")
def get_evaluation_summary(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Get side-by-side evaluation score summaries for the user's experiments.
    """
    summaries = experiment_service.summarize_experiments(session, user.id)
    return {
        exp_name: {
            "count": summary.count,
            "mean": summary.mean,
            "median": summary.median,
            "min_score": summary.min_score,
            "max_score": summary.max_score,
            "std_dev": summary.std_dev,
        }
        for exp_name, summary in summaries.items()
    }


class EvaluationRequest(BaseModel):
    message_id: int
    reference_answer: str | None = Field(default=None, max_length=20_000)
    provider: str | None = Field(default=None, description="Judge provider; defaults to the one that wrote the answer")
    model: str | None = None
    evaluator: str = Field(default="builtin", description="builtin, ragas or deepeval (see GET /api/evaluators)")


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    conversation_id: int | None
    evaluator: str
    judge_provider: str
    judge_model: str
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    context_recall: float | None
    hallucination: float | None
    rationale: str | None
    reference_answer: str | None
    rouge_l: float | None
    context_overlap: float | None
    created_at: datetime


class EvaluationHistory(BaseModel):
    items: list[EvaluationOut]
    total: int
    averages: dict[str, float | None]


@router.post("/api/evaluations", response_model=EvaluationOut, status_code=201)
async def evaluate_answer(
    payload: EvaluationRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    factory: ProviderFactory = Depends(get_provider_factory),
):
    """Score an assistant answer (faithfulness, answer relevancy, context
    precision, and context recall when a reference answer is given) with the
    built-in LLM judge, Ragas or DeepEval, judged by your own provider."""
    try:
        evaluation = await rag_evaluation.evaluate_message(
            session, user.id, payload.message_id, payload.reference_answer,
            provider=payload.provider, model=payload.model, factory=factory, evaluator=payload.evaluator,
        )
    except ChatError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    session.commit()
    return evaluation


@router.get("/api/evaluators")
def list_evaluators(user: User = Depends(get_current_user)):
    """The ways answers can be scored, and whether each is installed on this server."""
    return evaluators.available()


@router.get("/api/evaluations", response_model=EvaluationHistory)
def evaluation_history(
    conversation_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Past evaluations, newest first, with the average of each metric."""
    items, total, averages = rag_evaluation.list_evaluations(session, user.id, limit, offset, conversation_id)
    return {"items": items, "total": total, "averages": averages}
