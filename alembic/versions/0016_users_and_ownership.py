"""Users table and per-user ownership

Revision ID: 0016_users_and_ownership
Revises: 0015_saved_search
Create Date: 2026-09-30 12:00:00.000000

Adds the users table (authentication used to live in process memory) and
gives every user-owned table a user_id foreign key:

- documents, groups, provider_keys, saved_searches: owner required.
- search_query_logs, unmatched_searches, audit_logs: owner recorded so
  analytics and history can be scoped to the requesting user.

Rows written before this migration have no resolvable owner (documents and
saved searches stored a username string, other tables stored nothing). If any
exist, they are assigned to a placeholder user named "legacy-owner" whose
password hash can never verify, so the data is kept but nobody can log in as
that user until an operator reassigns it.

Also brings the migration history back in line with the models: creates the
audit_logs table (its model shipped without a migration) and drops
chunks.created_at, which no model maps.
"""
from alembic import op
import sqlalchemy as sa


revision = '0016_users_and_ownership'
down_revision = '0015_saved_search'
branch_labels = None
depends_on = None

LEGACY_USERNAME = "legacy-owner"
# Not a valid argon2 hash, so password verification always fails.
UNUSABLE_PASSWORD_HASH = "!"

OWNER_REQUIRED = ("documents", "groups", "provider_keys", "saved_searches")
OWNER_OPTIONAL = ("search_query_logs", "unmatched_searches")


def _fk_name(table):
    return f"fk_{table}_user_id_users"


def _legacy_owner_id(conn):
    has_rows = any(
        conn.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None
        for table in OWNER_REQUIRED
    )
    if not has_rows:
        return None
    conn.execute(
        sa.text(
            "INSERT INTO users (username, password_hash, created_at) "
            "VALUES (:username, :password_hash, CURRENT_TIMESTAMP)"
        ),
        {"username": LEGACY_USERNAME, "password_hash": UNUSABLE_PASSWORD_HASH},
    )
    return conn.execute(
        sa.text("SELECT id FROM users WHERE username = :username"),
        {"username": LEGACY_USERNAME},
    ).scalar()


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=150), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)

    conn = op.get_bind()
    legacy_owner_id = _legacy_owner_id(conn)

    # documents.user_id and saved_searches.user_id held usernames, not ids;
    # replace the columns rather than trying to convert their contents.
    with op.batch_alter_table('documents') as batch:
        batch.drop_index('ix_documents_user_id')
        batch.drop_column('user_id')
    with op.batch_alter_table('saved_searches') as batch:
        batch.drop_constraint('uq_saved_searches_user_id_search_name', type_='unique')
        batch.drop_index('ix_saved_searches_user_id')
        batch.drop_column('user_id')

    for table in OWNER_REQUIRED + OWNER_OPTIONAL:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('user_id', sa.Integer(), nullable=True))

    if legacy_owner_id is not None:
        for table in OWNER_REQUIRED:
            conn.execute(
                sa.text(f"UPDATE {table} SET user_id = :owner WHERE user_id IS NULL"),
                {"owner": legacy_owner_id},
            )

    for table in OWNER_REQUIRED + OWNER_OPTIONAL:
        with op.batch_alter_table(table) as batch:
            if table in OWNER_REQUIRED:
                batch.alter_column('user_id', existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(_fk_name(table), 'users', ['user_id'], ['id'], ondelete='CASCADE')
            batch.create_index(f'ix_{table}_user_id', ['user_id'])

    with op.batch_alter_table('saved_searches') as batch:
        batch.create_unique_constraint('uq_saved_searches_user_id_search_name', ['user_id', 'search_name'])

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'])

    with op.batch_alter_table('chunks') as batch:
        batch.drop_column('created_at')


def downgrade():
    with op.batch_alter_table('chunks') as batch:
        batch.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))

    op.drop_index('ix_audit_logs_user_id', table_name='audit_logs')
    op.drop_table('audit_logs')

    with op.batch_alter_table('saved_searches') as batch:
        batch.drop_constraint('uq_saved_searches_user_id_search_name', type_='unique')

    for table in OWNER_REQUIRED + OWNER_OPTIONAL:
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f'ix_{table}_user_id')
            batch.drop_constraint(_fk_name(table), type_='foreignkey')
            batch.drop_column('user_id')

    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch.create_index('ix_documents_user_id', ['user_id'])
    with op.batch_alter_table('saved_searches') as batch:
        batch.add_column(sa.Column('user_id', sa.String(length=255), nullable=False, server_default=''))
        batch.create_index('ix_saved_searches_user_id', ['user_id'])
        batch.create_unique_constraint('uq_saved_searches_user_id_search_name', ['user_id', 'search_name'])

    op.drop_index('ix_users_username', table_name='users')
    op.drop_table('users')
