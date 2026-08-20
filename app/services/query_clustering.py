from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.document import UnmatchedSearch
from app.services.jaccard_scoring import score_jaccard

def cluster_unmatched_queries(db: Session, start: Optional[datetime] = None, end: Optional[datetime] = None, threshold: float = 0.5) -> List[dict]:
    """
    Fetches UnmatchedSearch records within a timeframe, groups them by similarity,
    extracts a canonical query for each cluster, and counts occurrences.
    """
    query = db.query(UnmatchedSearch)
    
    if start:
        query = query.filter(UnmatchedSearch.timestamp >= start)
    if end:
        query = query.filter(UnmatchedSearch.timestamp <= end)
        
    records = query.all()
    
    clusters = []
    
    for record in records:
        q_text = record.query_text
        found_cluster = False
        
        for cluster in clusters:
            canonical = cluster["canonical_query"]
            similarity = score_jaccard(q_text, canonical)
            if similarity >= threshold:
                cluster["count"] += 1
                cluster["queries"].append(q_text)
                found_cluster = True
                break
                
        if not found_cluster:
            clusters.append({
                "canonical_query": q_text,
                "count": 1,
                "queries": [q_text]
            })
            
    # Optionally, pick the shortest or most frequent within cluster as canonical
    # For now, let's keep the first one as canonical and remove 'queries' to save output size if not needed,
    # but returning it might be useful.
    
    clusters.sort(key=lambda x: x["count"], reverse=True)
    return clusters
