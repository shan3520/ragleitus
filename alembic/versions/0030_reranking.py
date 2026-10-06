"""Reranking

Revision ID: 0030_reranking
Revises: 0029_experiment_concurrency
Create Date: 2026-10-06 16:00:00.000000

Users can rerank retrieved passages, with the server's own cross-encoder or
a provider's rerank API; experiment variants can compare with and without.
Reranking starts off for everyone.
"""
from alembic import op
import sqlalchemy as sa


revision = '0030_reranking'
down_revision = '0029_experiment_concurrency'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_settings') as batch:
        batch.add_column(sa.Column('rerank_provider', sa.String(length=100), nullable=False, server_default='none'))
        batch.add_column(sa.Column('rerank_model', sa.String(length=255), nullable=True))
    with op.batch_alter_table('experiment_variants') as batch:
        batch.add_column(sa.Column('rerank', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('experiment_variants') as batch:
        batch.drop_column('rerank')
    with op.batch_alter_table('user_settings') as batch:
        batch.drop_column('rerank_model')
        batch.drop_column('rerank_provider')
