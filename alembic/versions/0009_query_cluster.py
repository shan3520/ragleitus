"""query cluster

Revision ID: 0009_query_cluster
Revises: 0008_document_review_tracking
Create Date: 2026-08-20 22:33:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009_query_cluster'
down_revision = '0008_document_review_tracking'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('query_clusters',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=True),
    sa.Column('resolved_by_document_id', sa.Integer(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['resolved_by_document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('query_clusters')
