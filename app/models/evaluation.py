from sqlalchemy import Column, Integer, String, ForeignKey, Float, Text
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class Prompt(Base):
    __tablename__ = "prompts"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

    experiments = relationship("Experiment", back_populates="prompt", cascade="all, delete-orphan")

class Experiment(Base):
    __tablename__ = "experiments"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    prompt_id = Column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=True)
    # Owner. Experiments created before ownership existed have none and are shown to nobody.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    prompt = relationship("Prompt", back_populates="experiments")
    evaluations = relationship("Evaluation", back_populates="experiment", cascade="all, delete-orphan")

class Evaluation(Base):
    __tablename__ = "evaluations"
    id = Column(Integer, primary_key=True)
    score = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False)

    experiment = relationship("Experiment", back_populates="evaluations")

__all__ = ["Base", "Prompt", "Experiment", "Evaluation"]
