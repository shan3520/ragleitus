"""User token version

Revision ID: 0022_user_token_version
Revises: 0021_answer_evaluations
Create Date: 2026-09-30 19:00:00.000000

Access tokens carry the user's token_version; a password change bumps it,
so tokens issued before the change stop working.
"""
from alembic import op
import sqlalchemy as sa


revision = '0022_user_token_version'
down_revision = '0021_answer_evaluations'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default=sa.text('0')))


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('token_version')
