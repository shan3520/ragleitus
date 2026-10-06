from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .evaluation import Base


def _now():
    return datetime.now(timezone.utc)


class Experiment(Base):
    """A set of questions answered by several variants (prompt, model,
    retrieval) so their answers and scores can be compared."""

    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    # Legacy: the prompt the old score-only experiments referred to.
    prompt_id = Column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=True)
    # Owner. Experiments created before ownership existed have none and are shown to nobody.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    # draft -> queued -> running -> completed | failed
    status = Column(String(20), nullable=False, default="draft", server_default="draft")
    # [{"question": str, "reference_answer": str | None}, ...]
    cases = Column(JSON, nullable=True)
    # Only search these documents; all of the owner's when empty.
    document_ids = Column(JSON, nullable=True)
    # Score each answer with the LLM judge; judge_provider/_model default to each variant's own.
    evaluate = Column(Boolean, nullable=False, default=True, server_default="1")
    # builtin | ragas | deepeval (see app.services.evaluators)
    evaluator = Column(String(20), nullable=False, default="builtin", server_default="builtin")
    judge_provider = Column(String(100), nullable=True)
    judge_model = Column(String(255), nullable=True)
    # How many answers (question x variant) are worked on at once.
    concurrency = Column(Integer, nullable=False, default=1, server_default="1")
    # Identifies the run that owns the experiment; a newer run takes over.
    run_token = Column(String(36), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    prompt = relationship("Prompt")  # legacy, see prompt_id
    evaluations = relationship("Evaluation", back_populates="experiment", cascade="all, delete-orphan")
    variants = relationship(
        "ExperimentVariant", back_populates="experiment", cascade="all, delete-orphan",
        order_by="ExperimentVariant.position", passive_deletes=True,
    )


class ExperimentVariant(Base):
    __tablename__ = "experiment_variants"

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    label = Column(String(100), nullable=False)
    # NULL: the built-in system prompt (or a prompt deleted since).
    prompt_version_id = Column(Integer, ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True)
    # The prompt as it was named when the experiment was created ("Concise v2",
    # "Built-in prompt"), so results still say what they used if it is deleted.
    prompt_label = Column(String(300), nullable=False)
    provider = Column(String(100), nullable=False)
    model = Column(String(255), nullable=False)
    # hybrid | dense | keyword
    retrieval = Column(String(20), nullable=False, default="hybrid")
    top_k = Column(Integer, nullable=False)

    experiment = relationship("Experiment", back_populates="variants")
    prompt_version = relationship("PromptVersion")


class ExperimentResult(Base):
    """One variant's answer to one question, with its cost and scores."""

    __tablename__ = "experiment_results"

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(Integer, ForeignKey("experiment_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    case_index = Column(Integer, nullable=False)
    answer = Column(Text, nullable=True)
    citations = Column(JSON, nullable=True)
    # The passages given to the model: number, document, page, chunk and text.
    context = Column(JSON, nullable=True)
    latency_ms = Column(Float, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
    faithfulness = Column(Float, nullable=True)
    answer_relevancy = Column(Float, nullable=True)
    context_precision = Column(Float, nullable=True)
    context_recall = Column(Float, nullable=True)
    hallucination = Column(Float, nullable=True)
    rouge_l = Column(Float, nullable=True)
    judge_rationale = Column(Text, nullable=True)
    # Why this answer (or its evaluation) failed; the run goes on with the next.
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("variant_id", "case_index", name="uq_experiment_results_variant_id_case_index"),)


__all__ = ["Experiment", "ExperimentVariant", "ExperimentResult"]
