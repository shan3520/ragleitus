"""Initial migration

Revision ID: 0001_initial
Revises: 
Create Date: 2026-08-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create prompts table
    op.create_table(
        'prompts',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
    )

    # Create experiments table
    op.create_table(
        'experiments',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('prompt_id', sa.Integer, sa.ForeignKey('prompts.id', ondelete='CASCADE'), nullable=True),
    )

    # Create evaluations table
    op.create_table(
        'evaluations',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('experiment_id', sa.Integer, sa.ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False),
    )

    # Create provider_keys table
    op.create_table(
        'provider_keys',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('encrypted_key', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('provider_keys')
    op.drop_table('evaluations')
    op.drop_table('experiments')
    op.drop_table('prompts')
