import pytest
from datetime import datetime, timedelta, timezone
from app.models.document import SearchQueryLog, DocumentRetrievalLog, Document
from app.services.usage_analytics import get_search_analytics, get_popular_searches, get_popular_documents
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
    result = get_search_analytics(db_session)
    assert result == {"top_queries": [], "top_documents": []}

def test_get_search_analytics_with_data(db_session):
    now = datetime.now(timezone.utc)
    
    doc1 = Document(title="Doc1", status="ready")
    doc2 = Document(title="Doc2", status="ready")
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
    
    doc1 = Document(title="Doc1", status="ready")
    doc2 = Document(title="Doc2", status="ready")
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
    
    doc1 = Document(title="Doc1", status="ready")
    doc2 = Document(title="Doc2", status="ready")
    doc3 = Document(title="Doc3", status="ready")
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
