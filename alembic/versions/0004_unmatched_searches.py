"""unmatched searches

Revision ID: 0004_unmatched
Revises: 0003_document_groups
Create Date: 2026-08-20 01:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004_unmatched'
down_revision = '0003_document_groups'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'unmatched_searches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query_text', sa.String(length=255), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('unmatched_searches')
