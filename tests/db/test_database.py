import pytest
from sqlalchemy.orm import Session
from app.db.database import Base, SessionLocal, engine, get_db

def test_database_setup():
    assert engine is not None
    assert SessionLocal is not None
    assert Base is not None

def test_get_db_generator():
    db_gen = get_db()
    db = next(db_gen)
    assert isinstance(db, Session)
    try:
        pass
    finally:
        with pytest.raises(StopIteration):
            next(db_gen)
