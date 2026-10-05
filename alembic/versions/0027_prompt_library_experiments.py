"""Prompt library and experiments

Revision ID: 0027_prompt_library_experiments
Revises: 0026_embedding_settings
Create Date: 2026-10-06 09:00:00.000000

Prompts get an owner, a description and versions (prompt_versions); a
conversation can use one as its system prompt. Experiments get questions,
variants (prompt version, provider, model, retrieval strategy) and one
result per variant and question, with cost and judge scores.

Existing prompts and experiments have no owner and stay invisible, as
before; the legacy evaluations table is kept for /api/evaluations/summary.
"""
from alembic import op
import sqlalchemy as sa


revision = '0027_prompt_library_experiments'
down_revision = '0026_embedding_settings'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('prompts') as batch:
        batch.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch.add_column(sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key('fk_prompts_user_id_users', 'users', ['user_id'], ['id'], ondelete='CASCADE')
        batch.create_index('ix_prompts_user_id', ['user_id'])

    op.create_table(
        'prompt_versions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('prompt_id', sa.Integer(), sa.ForeignKey('prompts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('template', sa.Text(), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('prompt_id', 'version', name='uq_prompt_versions_prompt_id_version'),
    )
    op.create_index('ix_prompt_versions_prompt_id', 'prompt_versions', ['prompt_id'])

    with op.batch_alter_table('experiments') as batch:
        batch.add_column(sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'))
        batch.add_column(sa.Column('cases', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('document_ids', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('evaluate', sa.Boolean(), nullable=False, server_default='1'))
        batch.add_column(sa.Column('judge_provider', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('judge_model', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('run_token', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('error', sa.Text(), nullable=True))
        batch.add_column(sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'experiment_variants',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('experiment_id', sa.Integer(), sa.ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('prompt_version_id', sa.Integer(), sa.ForeignKey('prompt_versions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('prompt_label', sa.String(length=300), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=255), nullable=False),
        sa.Column('retrieval', sa.String(length=20), nullable=False),
        sa.Column('top_k', sa.Integer(), nullable=False),
    )
    op.create_index('ix_experiment_variants_experiment_id', 'experiment_variants', ['experiment_id'])

    op.create_table(
        'experiment_results',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('experiment_id', sa.Integer(), sa.ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('variant_id', sa.Integer(), sa.ForeignKey('experiment_variants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('case_index', sa.Integer(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('citations', sa.JSON(), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('faithfulness', sa.Float(), nullable=True),
        sa.Column('answer_relevancy', sa.Float(), nullable=True),
        sa.Column('context_precision', sa.Float(), nullable=True),
        sa.Column('context_recall', sa.Float(), nullable=True),
        sa.Column('hallucination', sa.Float(), nullable=True),
        sa.Column('rouge_l', sa.Float(), nullable=True),
        sa.Column('judge_rationale', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('variant_id', 'case_index', name='uq_experiment_results_variant_id_case_index'),
    )
    op.create_index('ix_experiment_results_experiment_id', 'experiment_results', ['experiment_id'])
    op.create_index('ix_experiment_results_variant_id', 'experiment_results', ['variant_id'])

    with op.batch_alter_table('conversations') as batch:
        batch.add_column(sa.Column('prompt_version_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_conversations_prompt_version_id_prompt_versions', 'prompt_versions',
            ['prompt_version_id'], ['id'], ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('conversations') as batch:
        batch.drop_constraint('fk_conversations_prompt_version_id_prompt_versions', type_='foreignkey')
        batch.drop_column('prompt_version_id')
    op.drop_table('experiment_results')
    op.drop_table('experiment_variants')
    with op.batch_alter_table('experiments') as batch:
        for column in ('finished_at', 'started_at', 'created_at', 'error', 'run_token', 'judge_model',
                       'judge_provider', 'evaluate', 'document_ids', 'cases', 'status'):
            batch.drop_column(column)
    op.drop_table('prompt_versions')
    with op.batch_alter_table('prompts') as batch:
        batch.drop_index('ix_prompts_user_id')
        batch.drop_constraint('fk_prompts_user_id_users', type_='foreignkey')
        batch.drop_column('created_at')
        batch.drop_column('description')
        batch.drop_column('user_id')
