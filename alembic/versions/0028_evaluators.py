"""Evaluators

Revision ID: 0028_evaluators
Revises: 0027_prompt_library_experiments
Create Date: 2026-10-06 12:00:00.000000

Answers can be scored by RAGForge's own judge, Ragas or DeepEval. Records
which one produced each evaluation (and which one an experiment uses), and
lets a judge score be null when the evaluator could not score that metric.
Existing rows were all produced by the built-in judge.
"""
from alembic import op
import sqlalchemy as sa


revision = '0028_evaluators'
down_revision = '0027_prompt_library_experiments'
branch_labels = None
depends_on = None

SCORES = ('faithfulness', 'answer_relevancy', 'context_precision', 'hallucination')


def upgrade():
    with op.batch_alter_table('answer_evaluations') as batch:
        batch.add_column(sa.Column('evaluator', sa.String(length=20), nullable=False, server_default='builtin'))
        for column in SCORES:
            batch.alter_column(column, existing_type=sa.Float(), nullable=True)
    with op.batch_alter_table('experiments') as batch:
        batch.add_column(sa.Column('evaluator', sa.String(length=20), nullable=False, server_default='builtin'))


def downgrade():
    with op.batch_alter_table('experiments') as batch:
        batch.drop_column('evaluator')
    op.execute("DELETE FROM answer_evaluations WHERE " + " OR ".join(f"{c} IS NULL" for c in SCORES))
    with op.batch_alter_table('answer_evaluations') as batch:
        for column in SCORES:
            batch.alter_column(column, existing_type=sa.Float(), nullable=False)
        batch.drop_column('evaluator')
