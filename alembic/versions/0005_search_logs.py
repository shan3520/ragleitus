"""search logs

Revision ID: 0005_search_logs
Revises: 0004_unmatched
Create Date: 2026-08-20 01:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005_search_logs'
down_revision = '0004_unmatched'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'search_query_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query_text', sa.String(length=255), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_search_query_logs_query_text'), 'search_query_logs', ['query_text'], unique=False)
    op.create_index(op.f('ix_search_query_logs_timestamp'), 'search_query_logs', ['timestamp'], unique=False)

    op.create_table(
        'document_retrieval_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query_log_id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['query_log_id'], ['search_query_logs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_retrieval_logs_document_id'), 'document_retrieval_logs', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_retrieval_logs_query_log_id'), 'document_retrieval_logs', ['query_log_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_document_retrieval_logs_query_log_id'), table_name='document_retrieval_logs')
    op.drop_index(op.f('ix_document_retrieval_logs_document_id'), table_name='document_retrieval_logs')
    op.drop_table('document_retrieval_logs')
    
    op.drop_index(op.f('ix_search_query_logs_timestamp'), table_name='search_query_logs')
    op.drop_index(op.f('ix_search_query_logs_query_text'), table_name='search_query_logs')
    op.drop_table('search_query_logs')
