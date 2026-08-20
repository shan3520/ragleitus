"""search_feedback

Revision ID: 0006_search_feedback
Revises: 0005_search_logs
Create Date: 2026-08-20 18:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006_search_feedback'
down_revision = '0005_search_logs'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'search_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('search_log_id', sa.Integer(), nullable=False),
        sa.Column('is_positive', sa.Boolean(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['search_log_id'], ['search_query_logs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_search_feedback_search_log_id'), 'search_feedback', ['search_log_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_search_feedback_search_log_id'), table_name='search_feedback')
    op.drop_table('search_feedback')
