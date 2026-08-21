"""search duration ms

Revision ID: 0014_search_duration_ms
Revises: 0013_document_retrieval_opened_at
Create Date: 2026-08-21 15:00:00.000000

Adds search_query_logs.duration_ms and unmatched_searches.duration_ms to
record the execution time of search queries in milliseconds.

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0014_search_duration_ms'
down_revision = '0013_document_retrieval_opened_at'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'search_query_logs',
        sa.Column('duration_ms', sa.Float(), nullable=True),
    )
    op.add_column(
        'unmatched_searches',
        sa.Column('duration_ms', sa.Float(), nullable=True),
    )


def downgrade():
    op.drop_column('unmatched_searches', 'duration_ms')
    op.drop_column('search_query_logs', 'duration_ms')
