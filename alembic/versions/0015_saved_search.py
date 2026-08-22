"""Add SavedSearch

Revision ID: 0015_saved_search
Revises: 0014_search_duration_ms
Create Date: 2026-08-23 00:30:00.000000

Adds the saved_searches table persisting user-defined search configurations
(query text plus optional applied filters) under a per-user unique name.

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0015_saved_search'
down_revision = '0014_search_duration_ms'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'saved_searches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('search_name', sa.String(length=255), nullable=False),
        sa.Column('query_text', sa.String(length=255), nullable=False),
        sa.Column('applied_filters', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'search_name', name='uq_saved_searches_user_id_search_name'),
    )
    op.create_index('ix_saved_searches_user_id', 'saved_searches', ['user_id'])


def downgrade():
    op.drop_index('ix_saved_searches_user_id', table_name='saved_searches')
    op.drop_table('saved_searches')
