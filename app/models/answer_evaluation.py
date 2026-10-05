from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .evaluation import Base


class AnswerEvaluation(Base):
    """Quality scores for one assistant answer, from an evaluator plus lexical baselines.

    Judge scores are 0..1, or null when the evaluator could not score that
    metric (Ragas has no faithfulness for an answer without claims, for
    example). `context_recall` needs a reference answer and is null without
    one; `hallucination` is 1 - faithfulness unless the evaluator measures it.
    """

    __tablename__ = "answer_evaluations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    # builtin | ragas | deepeval (see app.services.evaluators)
    evaluator = Column(String(20), nullable=False, default="builtin", server_default="builtin")
    judge_provider = Column(String(100), nullable=False)
    judge_model = Column(String(255), nullable=False)
    faithfulness = Column(Float, nullable=True)
    answer_relevancy = Column(Float, nullable=True)
    context_precision = Column(Float, nullable=True)
    context_recall = Column(Float, nullable=True)
    hallucination = Column(Float, nullable=True)
    rationale = Column(Text, nullable=True)
    reference_answer = Column(Text, nullable=True)
    # Lexical baselines: ROUGE-L F1 against the reference (if given) and word
    # overlap between the answer and the retrieved context.
    rouge_l = Column(Float, nullable=True)
    context_overlap = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    message = relationship("Message")

    @property
    def conversation_id(self) -> int | None:
        return self.message.conversation_id if self.message is not None else None


__all__ = ["AnswerEvaluation"]
