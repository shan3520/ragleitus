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
        db.add(UnmatchedSearch(query_text="what is an apple", timestamp=now))
        db.add(UnmatchedSearch(query_text="an apple is what", timestamp=now))
        
        db.commit()
        
        clusters = cluster_unmatched_queries(db, threshold=0.4)
        
        assert len(clusters) > 0
        assert "canonical_query" in clusters[0]
        assert "count" in clusters[0]
        assert "queries" in clusters[0]
        
        # Verify order by count desc
        counts = [c["count"] for c in clusters]
        assert counts == sorted(counts, reverse=True)
        
    finally:
        db.close()
