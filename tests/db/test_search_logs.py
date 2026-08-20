import asyncio
import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.evaluation import Base
# ensure models are loaded
from app.models.document import Document, SearchQueryLog, DocumentRetrievalLog
from app.services.document_search import search_documents

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()

def test_search_logs_saved_on_match(session):
    doc1 = Document(title="Test Doc 1", content="This is a test document.", status="ready")
    session.add(doc1)
    session.commit()

    bg_tasks = BackgroundTasks()
    
    matches = search_documents(
        documents=[doc1], 
        query="test", 
        session=session, 
        background_tasks=bg_tasks
    )
    
    assert len(matches) == 1
    assert len(bg_tasks.tasks) == 1
    
    # Execute background tasks
    for task in bg_tasks.tasks:
        task.func(*task.args, **task.kwargs)
        
    # Check DB
    query_logs = session.query(SearchQueryLog).all()
    assert len(query_logs) == 1
    assert query_logs[0].query_text == "test"
    
    retrievals = session.query(DocumentRetrievalLog).all()
    assert len(retrievals) == 1
    assert retrievals[0].query_log_id == query_logs[0].id
    assert retrievals[0].document_id == doc1.id

def test_search_logs_saved_on_unmatched(session):
    doc1 = Document(title="Test Doc 1", content="This is a test document.", status="ready")
    session.add(doc1)
    session.commit()

    bg_tasks = BackgroundTasks()
    
    matches = search_documents(
        documents=[doc1], 
        query="notfound", 
        session=session, 
        background_tasks=bg_tasks
    )
    
    assert len(matches) == 0
    assert len(bg_tasks.tasks) == 1
    
    # Execute background tasks
    for task in bg_tasks.tasks:
        task.func(*task.args, **task.kwargs)
        
    query_logs = session.query(SearchQueryLog).all()
    assert len(query_logs) == 0
