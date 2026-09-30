from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.models import Base


def _config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_alembic_upgrade_head_runs():
    command.upgrade(_config("sqlite:///:memory:"), "head")


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'schema.db'}"
    command.upgrade(_config(url), "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models and migrations disagree: {diff}"


def test_ownership_migration_keeps_existing_rows_under_legacy_owner(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "0015_saved_search")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO documents (title, status, user_id) VALUES ('old doc', 'ready', 'alice')"))
        conn.execute(text(
            "INSERT INTO saved_searches (user_id, search_name, query_text) VALUES ('alice', 'mine', 'q')"
        ))

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        owner = conn.execute(text("SELECT id, password_hash FROM users WHERE username = 'legacy-owner'")).one()
        assert owner.password_hash == "!"
        assert conn.execute(text("SELECT user_id FROM documents")).scalar() == owner.id
        assert conn.execute(text("SELECT user_id FROM saved_searches")).scalar() == owner.id


def test_ownership_migration_skips_legacy_owner_on_empty_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    command.upgrade(_config(url), "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar() == 0


def test_ownership_migration_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'down.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0015_saved_search")
    command.upgrade(cfg, "head")
