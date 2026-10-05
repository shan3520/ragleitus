import sys
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

# ensure repo root is on sys.path
from pathlib import Path
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name:
    fileConfig(config.config_file_name)

# Import the application's models to populate target_metadata.
from app.models import Base  # noqa: E402
from app.db.schema import include_object  # noqa: E402

# An explicit sqlalchemy.url (set by tests or on the command line) wins;
# otherwise use the application's configured database.
if not config.get_main_option("sqlalchemy.url"):
    from app.core.config import settings

    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, include_object=include_object)

    with context.begin_transaction():
        context.run_migrations()


def _widen_version_table(connection):
    """Some revision ids here are longer than the VARCHAR(32) Alembic gives
    alembic_version.version_num by default. SQLite ignores the length;
    PostgreSQL rejects the update. Create or widen the column before
    migrating (this also unsticks a database that stopped at 0012)."""
    if connection.dialect.name != "postgresql":
        return
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        "version_num VARCHAR(255) NOT NULL, "
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    connection.exec_driver_sql("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")
    connection.commit()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _widen_version_table(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
