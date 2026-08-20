"""document created_at backfill

Revision ID: 0012_document_created_at
Revises: 0011_document_feedback
Create Date: 2026-08-21 00:30:00.000000

The documents.created_at column itself has existed in the migration
history since 0002_document_chunk; the ORM model now maps it as well.
This migration only backfills rows that predate the column so they are
not permanently excluded from created_at-based filtering.

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '0012_document_created_at'
down_revision = '0011_document_feedback'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE documents SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
    )


def downgrade():
    pass
