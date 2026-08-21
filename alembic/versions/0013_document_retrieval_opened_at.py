"""document retrieval opened_at

Revision ID: 0013_document_retrieval_opened_at
Revises: 0012_document_created_at
Create Date: 2026-08-21 15:00:00.000000

Adds document_retrieval_logs.opened_at to record when a user opens a
retrieved document from their search results.

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0013_document_retrieval_opened_at'
down_revision = '0012_document_created_at'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'document_retrieval_logs',
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column('document_retrieval_logs', 'opened_at')
