"""add document review tracking

Revision ID: 0008_document_review_tracking
Revises: 0007_add_generated_answer
Create Date: 2026-08-20 21:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0008_document_review_tracking'
down_revision = '0007_add_generated_answer'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('documents', sa.Column('last_reviewed_at', sa.DateTime(), nullable=True))
    op.add_column('documents', sa.Column('review_status', sa.String(length=50), nullable=True))


def downgrade():
    op.drop_column('documents', 'review_status')
    op.drop_column('documents', 'last_reviewed_at')
