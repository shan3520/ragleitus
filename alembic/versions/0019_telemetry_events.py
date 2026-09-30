"""Telemetry events

Revision ID: 0019_telemetry_events
Revises: 0018_document_indexing
Create Date: 2026-09-30 15:00:00.000000

One row per LLM call: provider, model, latency, time to first token, token
usage (flagged when estimated) and cost.
"""
from alembic import op
import sqlalchemy as sa


revision = '0019_telemetry_events'
down_revision = '0018_document_indexing'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'telemetry_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=True),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('operation', sa.String(length=50), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error_type', sa.String(length=100), nullable=True),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('ttft_ms', sa.Float(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('tokens_estimated', sa.Boolean(), nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_telemetry_events_user_id', 'telemetry_events', ['user_id'])
    op.create_index('ix_telemetry_events_conversation_id', 'telemetry_events', ['conversation_id'])
    op.create_index('ix_telemetry_events_created_at', 'telemetry_events', ['created_at'])


def downgrade():
    op.drop_index('ix_telemetry_events_created_at', table_name='telemetry_events')
    op.drop_index('ix_telemetry_events_conversation_id', table_name='telemetry_events')
    op.drop_index('ix_telemetry_events_user_id', table_name='telemetry_events')
    op.drop_table('telemetry_events')
