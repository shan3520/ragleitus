"""Schema objects that exist in the database but not on the models.

The full-text search column on chunks and its index are PostgreSQL-only
(migration 0025), so they cannot be declared on the Chunk model, which also
has to work on SQLite. Alembic's autogenerate would otherwise offer to drop
them; `include_object` hides them from the comparison.
"""

DATABASE_ONLY = {
    ("column", "chunks", "search_vector"),
    ("index", "chunks", "ix_chunks_search_vector"),
}


def include_object(obj, name, type_, reflected, compare_to):
    if reflected and compare_to is None:
        table = obj.table.name if hasattr(obj, "table") else None
        if (type_, table, name) in DATABASE_ONLY:
            return False
    return True
