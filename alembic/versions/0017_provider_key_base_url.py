"""Provider key base URL and one key per provider

Revision ID: 0017_provider_key_base_url
Revises: 0016_users_and_ownership
Create Date: 2026-09-30 13:00:00.000000

Adds provider_keys.base_url for self-hosted OpenAI-compatible servers, and
makes (user_id, provider) unique: a user has at most one key per provider and
saving a new one replaces the old. If duplicates exist, the newest key for
each (user, provider) is kept.
"""
from alembic import op
import sqlalchemy as sa


revision = '0017_provider_key_base_url'
down_revision = '0016_users_and_ownership'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "DELETE FROM provider_keys WHERE id NOT IN ("
        "SELECT MAX(id) FROM provider_keys GROUP BY user_id, provider)"
    )
    with op.batch_alter_table('provider_keys') as batch:
        batch.add_column(sa.Column('base_url', sa.String(length=500), nullable=True))
        batch.create_unique_constraint('uq_provider_keys_user_id_provider', ['user_id', 'provider'])


def downgrade():
    with op.batch_alter_table('provider_keys') as batch:
        batch.drop_constraint('uq_provider_keys_user_id_provider', type_='unique')
        batch.drop_column('base_url')
