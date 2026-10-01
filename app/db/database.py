"""Database engine and session factory.

The schema is owned by Alembic (`alembic upgrade head`); nothing here creates
or alters tables.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models import Base

DATABASE_URL = settings.database_url

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency that yields a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["Base", "engine", "SessionLocal", "get_db"]
