"""document feedback association

Revision ID: 0011_document_feedback
Revises: 0010_query_cluster_timestamp
Create Date: 2026-08-20 23:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0011_document_feedback'
down_revision = '0010_query_cluster_timestamp'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('document_feedback',
        sa.Column('search_feedback_id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['search_feedback_id'], ['search_feedback.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('search_feedback_id', 'document_id')
    )


def downgrade():
    op.drop_table('document_feedback')
