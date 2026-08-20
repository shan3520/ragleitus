"""add generated answer

Revision ID: 0007_add_generated_answer
Revises: 0006_search_feedback
Create Date: 2026-08-20 18:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007_add_generated_answer'
down_revision = '0006_search_feedback'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('search_query_logs', sa.Column('generated_answer', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('search_query_logs', 'generated_answer')
