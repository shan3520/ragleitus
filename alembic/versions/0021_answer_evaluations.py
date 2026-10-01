"""Answer evaluations

Revision ID: 0021_answer_evaluations
Revises: 0020_conversations
Create Date: 2026-09-30 17:00:00.000000

LLM-judge scores (faithfulness, answer relevancy, context precision and
recall, hallucination) and lexical baselines for assistant answers.
"""
from alembic import op
import sqlalchemy as sa


revision = '0021_answer_evaluations'
down_revision = '0020_conversations'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'answer_evaluations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('message_id', sa.Integer(), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('judge_provider', sa.String(length=100), nullable=False),
        sa.Column('judge_model', sa.String(length=255), nullable=False),
        sa.Column('faithfulness', sa.Float(), nullable=False),
        sa.Column('answer_relevancy', sa.Float(), nullable=False),
        sa.Column('context_precision', sa.Float(), nullable=False),
        sa.Column('context_recall', sa.Float(), nullable=True),
        sa.Column('hallucination', sa.Float(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('reference_answer', sa.Text(), nullable=True),
        sa.Column('rouge_l', sa.Float(), nullable=True),
        sa.Column('context_overlap', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_answer_evaluations_user_id', 'answer_evaluations', ['user_id'])
    op.create_index('ix_answer_evaluations_message_id', 'answer_evaluations', ['message_id'])


def downgrade():
    op.drop_index('ix_answer_evaluations_message_id', table_name='answer_evaluations')
    op.drop_index('ix_answer_evaluations_user_id', table_name='answer_evaluations')
    op.drop_table('answer_evaluations')
