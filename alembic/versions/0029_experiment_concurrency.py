"""Experiment concurrency

Revision ID: 0029_experiment_concurrency
Revises: 0028_evaluators
Create Date: 2026-10-06 14:00:00.000000

How many answers an experiment works on at once. Existing experiments keep
running one at a time, as they did.
"""
from alembic import op
import sqlalchemy as sa


revision = '0029_experiment_concurrency'
down_revision = '0028_evaluators'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('experiments') as batch:
        batch.add_column(sa.Column('concurrency', sa.Integer(), nullable=False, server_default='1'))


def downgrade():
    with op.batch_alter_table('experiments') as batch:
        batch.drop_column('concurrency')
