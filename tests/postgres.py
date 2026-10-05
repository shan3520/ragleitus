"""Opt-in tests against a real PostgreSQL.

Set TEST_POSTGRES_URL to a database the tests may wipe, for example:

    docker run -d -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=pw postgres:16-alpine
    TEST_POSTGRES_URL=postgresql+psycopg://postgres:pw@127.0.0.1:55432/postgres pytest

Without it, tests marked `needs_postgres` are skipped, so the suite still runs
with no services.
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
needs_postgres = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not set")


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def fresh_postgres():
    """An engine on an emptied database, migrated to head."""
    from app.services import keyword_search

    keyword_search._stats_cache.clear()
    engine = create_engine(POSTGRES_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(POSTGRES_URL), "head")
    return engine
