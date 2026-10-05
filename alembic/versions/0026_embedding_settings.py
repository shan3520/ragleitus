"""Embedding settings

Revision ID: 0026_embedding_settings
Revises: 0025_chunk_search_vector
Create Date: 2026-10-05 17:00:00.000000

Users can embed their documents through one of their provider keys instead of
the server's local model. user_settings holds the choice; each document
records the model its vectors were made with, so retrieval embeds the
question with the same model. Existing documents keep NULL, which means the
local model they were indexed with.
"""
from alembic import op
import sqlalchemy as sa


revision = '0026_embedding_settings'
down_revision = '0025_chunk_search_vector'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_settings',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('embedding_provider', sa.String(length=100), nullable=False),
        sa.Column('embedding_model', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('embedding_provider', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('embedding_model', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('embedding_dimension', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('documents') as batch:
        batch.drop_column('embedding_dimension')
        batch.drop_column('embedding_model')
        batch.drop_column('embedding_provider')
    op.drop_table('user_settings')
