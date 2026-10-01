"""Conversations and messages

Revision ID: 0020_conversations
Revises: 0019_telemetry_events
Create Date: 2026-09-30 16:00:00.000000

Chat history. Assistant messages keep the passages they were given
(`context`), the ones they cited (`citations`), and the provider, model,
token usage and latency that produced them.
"""
from alembic import op
import sqlalchemy as sa


revision = '0020_conversations'
down_revision = '0019_telemetry_events'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=True),
        sa.Column('model', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])

    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('citations', sa.JSON(), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('provider', sa.String(length=100), nullable=True),
        sa.Column('model', sa.String(length=255), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('finish_reason', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])


def downgrade():
    op.drop_index('ix_messages_conversation_id', table_name='messages')
    op.drop_table('messages')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_table('conversations')
