"""Add Document and Chunk models

Revision ID: 0002_document_chunk
Revises: 0001_initial
Create Date: 2026-08-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002_document_chunk'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_documents_user_id', 'documents', ['user_id'])
    op.create_index('ix_documents_sha256', 'documents', ['sha256'])

    # Create chunks table
    op.create_table(
        'chunks',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('document_id', sa.Integer, sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sequence_order', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_chunks_document_id', 'chunks', ['document_id'])


def downgrade():
    op.drop_index('ix_chunks_document_id', table_name='chunks')
    op.drop_table('chunks')
    op.drop_index('ix_documents_sha256', table_name='documents')
    op.drop_index('ix_documents_user_id', table_name='documents')
    op.drop_table('documents')
