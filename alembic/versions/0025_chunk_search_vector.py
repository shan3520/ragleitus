"""Full-text search on chunks (PostgreSQL)

Revision ID: 0025_chunk_search_vector
Revises: 0024_document_index_claim
Create Date: 2026-10-05 15:00:00.000000

Keyword search used to load every chunk of a user's and score it in Python.
On PostgreSQL, chunks now carry a generated tsvector with a GIN index, so a
query reads only the chunks that contain its terms (see
app.services.keyword_search). SQLite keeps scoring in memory; nothing changes
there. The column is not on the Chunk model (see app.db.schema).
"""
from alembic import op


revision = '0025_chunk_search_vector'
down_revision = '0024_document_index_claim'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    # Must use the same configuration as app.services.keyword_search.TS_CONFIG.
    # Adding a stored generated column rewrites the table once, filling it in
    # for existing chunks.
    op.execute(
        "ALTER TABLE chunks ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, content)) STORED"
    )
    op.execute("CREATE INDEX ix_chunks_search_vector ON chunks USING gin (search_vector)")


def downgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    op.execute("DROP INDEX IF EXISTS ix_chunks_search_vector")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS search_vector")
