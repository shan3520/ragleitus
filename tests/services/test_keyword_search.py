"""Keyword search, on SQLite (in-memory BM25) and on PostgreSQL (full-text index).

The PostgreSQL cases run only when TEST_POSTGRES_URL is set (see
tests/postgres.py); the SQL they would run is still checked by compiling it
for PostgreSQL below.
"""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from app.db.schema import include_object
from app.models import Base
from app.models.document import Chunk, Document
from app.services import keyword_search
from tests.helpers import make_user
from tests.postgres import POSTGRES_URL, alembic_config, fresh_postgres, needs_postgres


@pytest.fixture(params=["sqlite", pytest.param("postgresql", marks=needs_postgres)])
def session(request, tmp_path):
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'keywords.db'}")
        Base.metadata.create_all(engine)
    else:
        engine = fresh_postgres()
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _document(session, user, title, *passages, status="ready"):
    doc = Document(user_id=user.id, title=title, status=status)
    session.add(doc)
    session.flush()
    chunks = [Chunk(document_id=doc.id, content=p, sequence_order=i) for i, p in enumerate(passages)]
    session.add_all(chunks)
    session.commit()
    return doc, [c.id for c in chunks]


def test_content_terms_drop_stop_words_and_duplicates():
    terms = ["what", "does", "the", "error", "e-4711", "e", "4711", "mean", "the", "error"]
    assert keyword_search.content_terms(terms) == ["error", "e-4711", "e", "4711", "mean"]
    assert keyword_search.content_terms(["what", "is", "it"]) == ["what", "is", "it"]
    assert len(keyword_search.content_terms([f"word{i}" for i in range(100)])) == keyword_search.MAX_TERMS


def test_ranks_the_passage_with_the_rare_term_first(session):
    user = make_user(session)
    _, error_ids = _document(
        session,
        user,
        "errors",
        "Error E-4711 means the upstream certificate expired.",
        "Error E-1000 means the disk is full.",
    )
    _, note_ids = _document(session, user, "notes", "An error happened at lunch.", "Parking rules for the office.")

    ranking = keyword_search.search(session, user.id, "What does error E-4711 mean?", limit=10)

    assert ranking[0] == error_ids[0]
    # Chunks that share only the common word "error" still match, ranked lower;
    # chunks that share no term do not match at all.
    assert sorted(ranking[1:]) == sorted([error_ids[1], note_ids[0]])


def test_only_the_users_ready_chunks_and_the_requested_documents(session):
    alice, bob = make_user(session), make_user(session)
    _, ready = _document(session, alice, "a", "Apples are red.")
    _, other = _document(session, alice, "b", "Apples are green.")
    _document(session, alice, "c", "Apples are yellow.", status="indexing")
    _document(session, bob, "d", "Apples are bob's.")
    doc_b = session.query(Document).filter_by(title="b").one()

    assert set(keyword_search.search(session, alice.id, "apples", limit=10)) == set(ready + other)
    assert keyword_search.search(session, alice.id, "apples", limit=10, document_ids=[doc_b.id]) == other
    assert keyword_search.search(session, alice.id, "apples", limit=1) in (ready, other)


def test_no_terms_or_no_match_returns_nothing(session):
    user = make_user(session)
    _document(session, user, "a", "Rockets fly.")

    assert keyword_search.search(session, user.id, "   ", limit=5) == []
    assert keyword_search.search(session, user.id, "?!", limit=5) == []
    assert keyword_search.search(session, user.id, "submarines", limit=5) == []
    assert keyword_search.search(session, user.id, "rockets", limit=0) == []
    assert keyword_search.search(session, make_user(session).id, "rockets", limit=5) == []


def test_versions_addresses_and_decimals_match(session):
    user = make_user(session)
    _, (version, contact, price, other) = _document(
        session,
        user,
        "notes",
        "Upgrade the gateway to version 3.2.1 before May.",
        "Write to ops@example.com for access.",
        "The licence costs 99.95 euros a seat.",
        "Version 4 of the handbook is out.",
    )

    assert keyword_search.search(session, user.id, "which version is 3.2.1?", limit=5)[0] == version
    assert keyword_search.search(session, user.id, "ops@example.com", limit=5)[0] == contact
    assert keyword_search.search(session, user.id, "99.95", limit=5) == [price]


def test_a_bare_number_finds_the_code_it_is_part_of(session):
    user = make_user(session)
    _, (code, other) = _document(
        session, user, "errors", "Error E-4711 means the certificate expired.", "Room 12 is closed."
    )

    assert keyword_search.search(session, user.id, "4711", limit=5) == [code]
    assert keyword_search.search(session, user.id, "E-4711", limit=5) == [code]


@needs_postgres
def test_postgres_parses_the_query_like_the_chunks():
    engine = fresh_postgres()
    with sessionmaker(bind=engine)() as session:
        lexemes = keyword_search.query_lexemes(session, "Is 3.2.1 at ops@example.com E-4711?")
    engine.dispose()
    assert lexemes[:3] == ["is", "3.2.1", "at"]
    # The parser reads E-4711 as a word and a signed number, in chunks too.
    assert {"ops@example.com", "e", "-4711"} <= set(lexemes)


def test_query_text_is_bound_never_inlined(session):
    user = make_user(session)
    _, ids = _document(session, user, "a", "It's a quote: O'Brien said hi.")

    # Quotes, tsquery operators and SQL in the query are just text.
    assert keyword_search.search(session, user.id, "O'Brien & | ! ) ; DROP TABLE chunks", limit=5) == ids


def _compile(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_postgres_statements_use_the_index_and_bound_parameters():
    ranking = _compile(keyword_search.ranking_statement(7, ["e", "4711"], [0.5, 2.0], 20, [1, 2]))
    # Every term is a bound parameter parsed by plainto_tsquery; terms match on any one.
    assert "chunks.search_vector @@ (plainto_tsquery('simple', %(term_0)s" in ranking
    assert "|| plainto_tsquery('simple', %(term_1)s" in ranking
    assert "ts_rank(chunks.search_vector, plainto_tsquery('simple', %(term_1)s" in ranking
    assert "documents.user_id = %(user_id_1)s" in ranking
    assert "documents.status = %(status_1)s" in ranking
    assert "documents.id IN (" in ranking
    assert "LIMIT %(param_1)s" in ranking
    assert "4711" not in ranking



def test_terms_are_weighted_by_rarity_and_very_common_ones_dropped():
    stats = keyword_search.TermStatistics({"error": 0.9, "certificate": 0.01}, floor=0.001)

    weighted = dict(keyword_search.weighted_terms(["error", "certificate", "e4711"], stats))
    assert set(weighted) == {"certificate", "e4711"}
    assert weighted["e4711"] > weighted["certificate"] > 0
    # Only common terms: keep them rather than search for nothing.
    assert [t for t, _ in keyword_search.weighted_terms(["error"], stats)] == ["error"]
    # A term the statistics don't list is rare, even when every listed term is common.
    assert keyword_search.TermStatistics({"error": 0.99}, floor=0.99).frequency("e4711") <= 0.005
    # Before the table is analysed every term weighs the same.
    assert keyword_search.weighted_terms(["error", "x"], None) == [("error", 1.0), ("x", 1.0)]


@needs_postgres
def test_postgres_migration_matches_models_and_uses_the_gin_index():
    engine = fresh_postgres()
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"include_object": include_object, "compare_type": True}),
            Base.metadata,
        )
        assert diff == [], f"models and migrations disagree: {diff}"

        # A realistic collection: one user with 20,000 chunks, one of which
        # mentions the term. The planner should reach it through the GIN index
        # rather than reading the user's chunks.
        conn.execute(text("INSERT INTO users (id, username, password_hash, token_version, created_at) VALUES (1, 'big', '!', 0, now())"))
        conn.execute(text("INSERT INTO documents (id, user_id, title, status) VALUES (1, 1, 'big', 'ready')"))
        conn.execute(text(
            "INSERT INTO chunks (document_id, content, sequence_order) "
            "SELECT 1, 'routine passage number ' || n || ' about lunch and parking', n "
            "FROM generate_series(1, 20000) AS n"
        ))
        conn.execute(text(
            "INSERT INTO chunks (document_id, content, sequence_order) "
            "VALUES (1, 'Error E-4711 means the upstream certificate expired.', 20001)"
        ))
        conn.commit()
        # VACUUM moves the bulk insert out of the GIN pending list, as
        # autovacuum would; ANALYZE gives the planner real statistics.
        autocommit = conn.execution_options(isolation_level="AUTOCOMMIT")
        autocommit.execute(text("VACUUM ANALYZE chunks"))
        autocommit.execute(text("VACUUM ANALYZE documents"))
        session = sessionmaker(bind=conn)()
        stats = keyword_search.term_statistics(session)
        assert stats.frequency("routine") > 0.9
        assert stats.frequency("certificate") < 0.01
        # "routine" is in every chunk, so the rare term decides the ranking.
        assert keyword_search.search(session, 1, "routine certificate", limit=3) == [20001]

        statement = keyword_search.ranking_statement(1, ["certificate"], [1.0], 10, None)
        compiled = statement.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True})
        plan = conn.exec_driver_sql(f"EXPLAIN {compiled}").scalars().all()
        assert any("ix_chunks_search_vector" in line for line in plan), plan

    command.downgrade(alembic_config(POSTGRES_URL), "0024_document_index_claim")
    with engine.connect() as conn:
        columns = conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'chunks'")
        ).scalars().all()
        assert "search_vector" not in columns
    command.upgrade(alembic_config(POSTGRES_URL), "head")
    engine.dispose()
