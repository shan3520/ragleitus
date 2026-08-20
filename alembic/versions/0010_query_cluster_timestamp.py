"""query cluster timestamp

Revision ID: 0010_query_cluster_timestamp
Revises: 0009_query_cluster
Create Date: 2026-08-20 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0010_query_cluster_timestamp'
down_revision = '0009_query_cluster'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('query_clusters', sa.Column('last_resolved_query_timestamp', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('query_clusters', 'last_resolved_query_timestamp')
