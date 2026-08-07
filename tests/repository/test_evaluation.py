import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.models import Base, Prompt, Experiment, Evaluation


def setup_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    # Enable SQLite foreign key enforcement for tests
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
    return engine


def test_foreign_keys_and_relationships():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    p = Prompt(name="prompt1")
    e = Experiment(name="exp1", prompt=p)
    ev = Evaluation(score=0.95, experiment=e)
    session.add(ev)
    session.commit()

    assert e.id is not None
    assert p.id is not None
    assert ev.experiment_id == e.id

    got = session.query(Evaluation).join(Experiment).join(Prompt).filter(Prompt.id == p.id).one()
    assert got.id == ev.id


def test_fk_enforced():
    engine = setup_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    bad = Evaluation(score=0.1, experiment_id=9999)
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()
