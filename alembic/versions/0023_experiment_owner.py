"""Experiment owner

Revision ID: 0023_experiment_owner
Revises: 0022_user_token_version
Create Date: 2026-10-01 09:00:00.000000

Experiments had no owner, so the evaluation summary showed every user's
experiments to everyone. Adds experiments.user_id. Existing experiments have
no recorded owner and keep NULL: they stay in the database but are returned
to nobody until an operator assigns them.
"""
from alembic import op
import sqlalchemy as sa


revision = '0023_experiment_owner'
down_revision = '0022_user_token_version'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('experiments') as batch:
        batch.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_experiments_user_id_users', 'users', ['user_id'], ['id'], ondelete='CASCADE')
        batch.create_index('ix_experiments_user_id', ['user_id'])


def downgrade():
    with op.batch_alter_table('experiments') as batch:
        batch.drop_index('ix_experiments_user_id')
        batch.drop_constraint('fk_experiments_user_id_users', type_='foreignkey')
        batch.drop_column('user_id')
