import datetime
from sqlalchemy.orm import Session
from app.models.document import UnmatchedSearch
from app.services.query_clustering import cluster_unmatched_queries
from app.db.database import get_db

def test_cluster_unmatched_queries():
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        db.query(UnmatchedSearch).delete()
        db.commit()
        
        # Add test data
        now = datetime.datetime.now(datetime.timezone.utc)
        db.add(UnmatchedSearch(query_text="how to reset password", timestamp=now))
        db.add(UnmatchedSearch(query_text="reset password", timestamp=now))
        db.add(UnmatchedSearch(query_text="forgot password", timestamp=now))
        
        search_apple = UnmatchedSearch(query_text="what is an apple", timestamp=now)
        db.add(search_apple)
        db.add(UnmatchedSearch(query_text="an apple is what", timestamp=now))
        
        db.commit()
        
        from app.models.query_cluster import QueryCluster
        cluster = QueryCluster(id=search_apple.id, status="regression")
        db.add(cluster)
        db.commit()
        
        clusters = cluster_unmatched_queries(db, threshold=0.4)
        
        assert len(clusters) > 0
        assert "canonical_query" in clusters[0]
        assert "count" in clusters[0]
        assert "queries" in clusters[0]
        assert "status" in clusters[0]
        
        statuses = [c["status"] for c in clusters]
        assert "regression" in statuses
        assert "open" in statuses
        
        # Verify order by count desc
        counts = [c["count"] for c in clusters]
        assert counts == sorted(counts, reverse=True)
        
    finally:
        db.close()

def test_mark_cluster_handled():
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        from app.models.query_cluster import QueryCluster
        from app.models.document import Document
        
        doc = Document(user_id="test_user", title="Test", content="Content", status="completed")
        db.add(doc)
        db.commit()
        
        cluster = QueryCluster(status="open")
        db.add(cluster)
        db.commit()
        
        from app.services.query_clustering import mark_cluster_handled
        updated_cluster = mark_cluster_handled(db, cluster.id, doc.id)
        
        assert updated_cluster is not None
        assert updated_cluster.status == "handled"
        assert updated_cluster.resolved_by_document_id == doc.id
        assert updated_cluster.resolved_at is not None
        
    finally:
        db.close()
