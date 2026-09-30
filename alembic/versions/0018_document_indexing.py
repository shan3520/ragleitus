"""Document indexing metadata

Revision ID: 0018_document_indexing
Revises: 0017_provider_key_base_url
Create Date: 2026-09-30 14:00:00.000000

Adds what background indexing needs: the uploaded filename and the last
indexing error on documents, and the source page and estimated token count on
chunks (so answers can cite a page).
"""
from alembic import op
import sqlalchemy as sa


revision = '0018_document_indexing'
down_revision = '0017_provider_key_base_url'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('filename', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('error', sa.Text(), nullable=True))
    with op.batch_alter_table('chunks') as batch:
        batch.add_column(sa.Column('page_number', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('token_count', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('chunks') as batch:
        batch.drop_column('token_count')
        batch.drop_column('page_number')
    with op.batch_alter_table('documents') as batch:
        batch.drop_column('error')
        batch.drop_column('filename')
