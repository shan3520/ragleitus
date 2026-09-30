from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from .evaluation import Base


class AnswerEvaluation(Base):
    """Quality scores for one assistant answer, from an LLM judge plus lexical baselines.

    Judge scores are 0..1. `context_recall` needs a reference answer and is
    null without one; `hallucination` is 1 - faithfulness.
    """

    __tablename__ = "answer_evaluations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    judge_provider = Column(String(100), nullable=False)
    judge_model = Column(String(255), nullable=False)
    faithfulness = Column(Float, nullable=False)
    answer_relevancy = Column(Float, nullable=False)
    context_precision = Column(Float, nullable=False)
    context_recall = Column(Float, nullable=True)
    hallucination = Column(Float, nullable=False)
    rationale = Column(Text, nullable=True)
    reference_answer = Column(Text, nullable=True)
    # Lexical baselines: ROUGE-L F1 against the reference (if given) and word
    # overlap between the answer and the retrieved context.
    rouge_l = Column(Float, nullable=True)
    context_overlap = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


__all__ = ["AnswerEvaluation"]
