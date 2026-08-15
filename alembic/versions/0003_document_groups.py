"""Add Group model and Document relation

Revision ID: 0003_document_groups
Revises: 0002_document_chunk
Create Date: 2026-08-15 22:10:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003_document_groups'
down_revision = '0002_document_chunk'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'groups',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('group_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_documents_groups', 'groups', ['group_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_constraint('fk_documents_groups', type_='foreignkey')
        batch_op.drop_column('group_id')
    op.drop_table('groups')
