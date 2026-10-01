import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.evaluation import Evaluation, Experiment
from app.services.experiment_service import summarize_experiments
from tests.helpers import make_user


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


def _experiment(session, name, user_id, scores):
    exp = Experiment(name=name, user_id=user_id)
    session.add(exp)
    session.flush()
    session.add_all([Evaluation(experiment_id=exp.id, score=s) for s in scores])
    session.flush()


def test_summaries_include_only_the_users_own_experiments(session):
    alice, bob = make_user(session), make_user(session)
    _experiment(session, "alice-a", alice.id, [0.8, 1.0])
    _experiment(session, "bob-b", bob.id, [0.1])
    _experiment(session, "legacy", None, [0.5])  # created before experiments had owners

    summaries = summarize_experiments(session, alice.id)
    assert list(summaries) == ["alice-a"]
    assert summaries["alice-a"].count == 2
    assert summaries["alice-a"].mean == pytest.approx(0.9)
    assert list(summarize_experiments(session, bob.id)) == ["bob-b"]
    assert summarize_experiments(session, make_user(session).id) == {}


def test_experiments_with_the_same_name_are_all_kept(session):
    alice = make_user(session)
    _experiment(session, "baseline", alice.id, [0.9, 0.8])
    _experiment(session, "baseline", alice.id, [0.1])
    summaries = summarize_experiments(session, alice.id)
    assert len(summaries) == 2
    assert summaries["baseline"].count == 2
    (other,) = [name for name in summaries if name != "baseline"]
    assert other.startswith("baseline (#") and summaries[other].count == 1
