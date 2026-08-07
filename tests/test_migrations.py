from alembic.config import Config
from alembic import command


def test_alembic_upgrade_head_runs():
    cfg = Config()
    # point alembic at the local alembic directory
    cfg.set_main_option("script_location", "alembic")
    # use in-memory sqlite per task instruction
    cfg.set_main_option("sqlalchemy.url", "sqlite:///:memory:")

    # Running upgrade to head should not raise and should complete
    command.upgrade(cfg, "head")
