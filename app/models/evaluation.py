from sqlalchemy import Column, Integer, ForeignKey, Float, Text
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class Evaluation(Base):
    """Legacy: a free-form score for an experiment (see /api/evaluations/summary)."""

    __tablename__ = "evaluations"
    id = Column(Integer, primary_key=True)
    score = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False)

    experiment = relationship("Experiment", back_populates="evaluations")


# Defined in their own modules; importable from here as before.
from .prompt import Prompt, PromptVersion  # noqa: E402
from .experiment import Experiment, ExperimentResult, ExperimentVariant  # noqa: E402

__all__ = ["Base", "Prompt", "PromptVersion", "Experiment", "ExperimentVariant", "ExperimentResult", "Evaluation"]
