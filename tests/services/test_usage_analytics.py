import pytest
from datetime import datetime, timedelta, timezone
from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document
from app.services.usage_analytics import get_search_analytics, get_popular_searches, get_popular_documents, get_daily_search_latency
from app.core.errors import NoSearchActivityError
from app.db.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)

def test_get_search_analytics_empty(db_session):
    # An empty activity window is an error state, not an empty result.
    with pytest.raises(NoSearchActivityError):
        get_search_analytics(db_session)

def test_get_search_analytics_raises_when_only_old_activity(db_session):
    # Activity exists in the table but none inside the requested window:
    # the zero-count check must be window-scoped, so this still raises
    # instead of returning {"top_queries": [], "top_documents": []}.
    now = datetime.now(timezone.utc)
    db_session.add(SearchQueryLog(query_text="ancient", timestamp=now - timedelta(days=60)))
    db_session.commit()

    with pytest.raises(NoSearchActivityError):
        get_search_analytics(db_session, days=30)

def test_get_search_analytics_excludes_logs_outside_window(db_session):
    now = datetime.now(timezone.utc)

    doc_recent = Document(user_id=1, title="RecentDoc", status="ready")
    doc_ancient = Document(user_id=1, title="AncientDoc", status="ready")
    db_session.add_all([doc_recent, doc_ancient])
    db_session.commit()

    recent_log = SearchQueryLog(query_text="recent query", timestamp=now)
    ancient_log = SearchQueryLog(query_text="ancient query", timestamp=now - timedelta(days=45))
    db_session.add_all([recent_log, ancient_log])
    db_session.commit()

    db_session.add_all([
        DocumentRetrievalLog(query_log_id=recent_log.id, document_id=doc_recent.id),
        DocumentRetrievalLog(query_log_id=ancient_log.id, document_id=doc_ancient.id),
    ])
    db_session.commit()

    result = get_search_analytics(db_session, days=30)

    # If the pre-aggregation window filter were dropped, the 45-day-old
    # query and its document would appear here.
    assert result["top_queries"] == [{"query": "recent query", "count": 1}]
    assert result["top_documents"] == [{"document_id": doc_recent.id, "count": 1}]

def test_get_popular_searches_excludes_logs_outside_window(db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all([
        SearchQueryLog(query_text="recent query", timestamp=now),
        SearchQueryLog(query_text="ancient query", timestamp=now - timedelta(days=45)),
    ])
    db_session.commit()

    result = get_popular_searches(db_session, days=30)
    assert result == [{"query": "recent query", "count": 1}]

def test_get_popular_documents_excludes_logs_outside_window(db_session):
    now = datetime.now(timezone.utc)

    doc_recent = Document(user_id=1, title="RecentDoc", status="ready")
    doc_ancient = Document(user_id=1, title="AncientDoc", status="ready")
    db_session.add_all([doc_recent, doc_ancient])
    db_session.commit()

    recent_log = SearchQueryLog(query_text="recent query", timestamp=now)
    ancient_log = SearchQueryLog(query_text="ancient query", timestamp=now - timedelta(days=45))
    db_session.add_all([recent_log, ancient_log])
    db_session.commit()

    db_session.add_all([
        DocumentRetrievalLog(query_log_id=recent_log.id, document_id=doc_recent.id),
        DocumentRetrievalLog(query_log_id=ancient_log.id, document_id=doc_ancient.id),
    ])
    db_session.commit()

    result = get_popular_documents(db_session, days=30)
    assert result == [{"document_id": doc_recent.id, "count": 1}]

def test_get_popular_searches_raises_on_empty_window(db_session):
    with pytest.raises(NoSearchActivityError):
        get_popular_searches(db_session, days=30)

def test_get_popular_documents_raises_on_empty_window(db_session):
    with pytest.raises(NoSearchActivityError):
        get_popular_documents(db_session, days=30)

def test_get_search_analytics_with_data(db_session):
    now = datetime.now(timezone.utc)
    
    doc1 = Document(user_id=1, title="Doc1", status="ready")
    doc2 = Document(user_id=1, title="Doc2", status="ready")
    db_session.add_all([doc1, doc2])
    db_session.commit()
    
    log1 = SearchQueryLog(query_text="apple", timestamp=now)
    log2 = SearchQueryLog(query_text="apple", timestamp=now)
    log3 = SearchQueryLog(query_text="banana", timestamp=now)
    log4 = SearchQueryLog(query_text="cherry", timestamp=now - timedelta(days=10))
    
    db_session.add_all([log1, log2, log3, log4])
    db_session.commit()
    
    r1 = DocumentRetrievalLog(query_log_id=log1.id, document_id=doc1.id)
    r2 = DocumentRetrievalLog(query_log_id=log2.id, document_id=doc2.id)
    r3 = DocumentRetrievalLog(query_log_id=log3.id, document_id=doc2.id)
    r4 = DocumentRetrievalLog(query_log_id=log4.id, document_id=doc1.id)
    
    db_session.add_all([r1, r2, r3, r4])
    db_session.commit()
    
    result = get_search_analytics(db_session, days=7)
    
    assert len(result["top_queries"]) == 2
    assert result["top_queries"][0] == {"query": "apple", "count": 2}
    assert result["top_queries"][1] == {"query": "banana", "count": 1}
    
    assert len(result["top_documents"]) == 2
    assert result["top_documents"][0] == {"document_id": doc2.id, "count": 2}
    assert result["top_documents"][1] == {"document_id": doc1.id, "count": 1}
    
def test_get_search_analytics_ties(db_session):
    now = datetime.now(timezone.utc)
    
    doc1 = Document(user_id=1, title="Doc1", status="ready")
    doc2 = Document(user_id=1, title="Doc2", status="ready")
    db_session.add_all([doc1, doc2])
    db_session.commit()
    
    log1 = SearchQueryLog(query_text="zebra", timestamp=now)
    log2 = SearchQueryLog(query_text="apple", timestamp=now)
    
    db_session.add_all([log1, log2])
    db_session.commit()
    
    r1 = DocumentRetrievalLog(query_log_id=log1.id, document_id=doc2.id)
    r2 = DocumentRetrievalLog(query_log_id=log2.id, document_id=doc1.id)
    
    db_session.add_all([r1, r2])
    db_session.commit()
    
    result = get_search_analytics(db_session)
    assert result["top_queries"][0]["query"] == "apple"
    assert result["top_queries"][1]["query"] == "zebra"
    
    assert result["top_documents"][0]["document_id"] == doc1.id
    assert result["top_documents"][1]["document_id"] == doc2.id

def test_get_popular_searches(db_session):
    now = datetime.now(timezone.utc)
    
    logs = [
        SearchQueryLog(query_text="apple", timestamp=now),
        SearchQueryLog(query_text="apple", timestamp=now),
        SearchQueryLog(query_text="apple", timestamp=now),
        SearchQueryLog(query_text="banana", timestamp=now),
        SearchQueryLog(query_text="banana", timestamp=now),
        SearchQueryLog(query_text="cherry", timestamp=now),
    ]
    db_session.add_all(logs)
    db_session.commit()
    
    result = get_popular_searches(db_session, limit=2)
    assert len(result) == 2
    assert result[0] == {"query": "apple", "count": 3}
    assert result[1] == {"query": "banana", "count": 2}

def test_get_popular_documents(db_session):
    now = datetime.now(timezone.utc)
    
    doc1 = Document(user_id=1, title="Doc1", status="ready")
    doc2 = Document(user_id=1, title="Doc2", status="ready")
    doc3 = Document(user_id=1, title="Doc3", status="ready")
    db_session.add_all([doc1, doc2, doc3])
    db_session.commit()
    
    log = SearchQueryLog(query_text="apple", timestamp=now)
    db_session.add(log)
    db_session.commit()
    
    r1 = DocumentRetrievalLog(query_log_id=log.id, document_id=doc1.id)
    r2 = DocumentRetrievalLog(query_log_id=log.id, document_id=doc1.id)
    r3 = DocumentRetrievalLog(query_log_id=log.id, document_id=doc1.id)
    r4 = DocumentRetrievalLog(query_log_id=log.id, document_id=doc2.id)
    r5 = DocumentRetrievalLog(query_log_id=log.id, document_id=doc2.id)
    r6 = DocumentRetrievalLog(query_log_id=log.id, document_id=doc3.id)
    
    db_session.add_all([r1, r2, r3, r4, r5, r6])
    db_session.commit()
    
    result = get_popular_documents(db_session, limit=2)
    assert len(result) == 2
    assert result[0] == {"document_id": doc1.id, "count": 3}
    assert result[1] == {"document_id": doc2.id, "count": 2}

def test_get_daily_search_latency_excludes_logs_outside_window(db_session):
    now = datetime.now(timezone.utc)

    db_session.add_all([
        SearchQueryLog(query_text="recent a", timestamp=now, duration_ms=100.0),
        SearchQueryLog(query_text="recent b", timestamp=now, duration_ms=300.0),
        SearchQueryLog(query_text="ancient", timestamp=now - timedelta(days=45), duration_ms=9000.0),
    ])
    db_session.commit()

    result = get_daily_search_latency(db_session, days=30)

    # The 45-day-old log sits outside the 30-day window. If the window
    # filter were dropped it would join today's group and inflate every
    # aggregate here: total 3 instead of 2, average ~3133 instead of 200,
    # max 9000 instead of 300.
    assert len(result) == 1
    assert result[0]["total_searches"] == 2
    assert result[0]["average_duration_ms"] == 200.0
    assert result[0]["max_duration_ms"] == 300.0

def test_get_daily_search_latency_groups_by_date(db_session):
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    db_session.add_all([
        SearchQueryLog(query_text="today 1", timestamp=now, duration_ms=50.0),
        SearchQueryLog(query_text="today 2", timestamp=now, duration_ms=150.0),
        SearchQueryLog(query_text="yesterday", timestamp=yesterday, duration_ms=400.0),
    ])
    db_session.commit()

    result = get_daily_search_latency(db_session, days=7)

    assert [row["date"] for row in result] == [
        yesterday.date().isoformat(),
        now.date().isoformat(),
    ]
    assert result[0] == {
        "date": yesterday.date().isoformat(),
        "total_searches": 1,
        "average_duration_ms": 400.0,
        "max_duration_ms": 400.0,
    }
    assert result[1]["total_searches"] == 2
    assert result[1]["average_duration_ms"] == 100.0
    assert result[1]["max_duration_ms"] == 150.0

def test_get_daily_search_latency_defaults_null_durations_to_zero(db_session):
    now = datetime.now(timezone.utc)

    db_session.add(SearchQueryLog(query_text="no timing", timestamp=now, duration_ms=None))
    db_session.commit()

    result = get_daily_search_latency(db_session, days=30)

    assert len(result) == 1
    assert result[0]["total_searches"] == 1
    assert result[0]["average_duration_ms"] == 0.0
    assert result[0]["max_duration_ms"] == 0.0

def test_get_daily_search_latency_empty_returns_empty_list(db_session):
    assert get_daily_search_latency(db_session, days=30) == []


def test_analytics_are_scoped_to_the_requested_user(db_session):
    now = datetime.now(timezone.utc)
    mine = SearchQueryLog(user_id=1, query_text="mine", timestamp=now, duration_ms=10.0)
    theirs = SearchQueryLog(user_id=2, query_text="theirs", timestamp=now, duration_ms=500.0)
    db_session.add_all([mine, theirs])
    db_session.commit()

    assert get_popular_searches(db_session, user_id=1) == [{"query": "mine", "count": 1}]
    assert get_search_analytics(db_session, user_id=1)["top_queries"] == [{"query": "mine", "count": 1}]
    latency = get_daily_search_latency(db_session, user_id=1)
    assert [row["max_duration_ms"] for row in latency] == [10.0]

    with pytest.raises(NoSearchActivityError):
        get_popular_searches(db_session, user_id=3)
