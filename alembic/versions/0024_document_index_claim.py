"""Document index claim

Revision ID: 0024_document_index_claim
Revises: 0023_experiment_owner
Create Date: 2026-10-05 09:00:00.000000

Indexing can run in several worker processes. Each run claims the document
with a token; a newer run takes over and an older one discards its work.
index_updated_at records when a document was last queued or claimed, so runs
lost to a crash or restart can be found and queued again.
"""
from alembic import op
import sqlalchemy as sa


revision = '0024_document_index_claim'
down_revision = '0023_experiment_owner'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('index_token', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('index_updated_at', sa.DateTime(timezone=True), nullable=True))
    # Chunk ids double as vector point ids and must never be reused (see the
    # Chunk model). SQLite reuses the highest deleted rowid unless the table
    # uses AUTOINCREMENT, which needs the table to be rebuilt.
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('chunks', recreate='always', table_kwargs={'sqlite_autoincrement': True}):
            pass


def downgrade():
    with op.batch_alter_table('documents') as batch:
        batch.drop_column('index_updated_at')
        batch.drop_column('index_token')
