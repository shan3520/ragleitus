from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.document import UnmatchedSearch
from app.services.jaccard_scoring import score_jaccard

def cluster_unmatched_queries(db: Session, start: Optional[datetime] = None, end: Optional[datetime] = None, threshold: float = 0.5, status: str = "open") -> List[dict]:
    """
    Fetches UnmatchedSearch records within a timeframe, groups them by similarity,
    extracts a canonical query for each cluster, and counts occurrences.
    """
    from app.models.query_cluster import QueryCluster
    from sqlalchemy import or_

    query = db.query(UnmatchedSearch, QueryCluster).outerjoin(
        QueryCluster, UnmatchedSearch.id == QueryCluster.id
    )
    
    if start:
        query = query.filter(UnmatchedSearch.timestamp >= start)
    if end:
        query = query.filter(UnmatchedSearch.timestamp <= end)

    if status == "open":
        query = query.filter(or_(QueryCluster.status == None, QueryCluster.status == "open"))
    elif status:
        query = query.filter(QueryCluster.status == status)
        
    records = query.all()
    
    clusters = []
    
    for record, q_cluster in records:
        q_text = record.query_text
        found_cluster = False
        
        for cluster in clusters:
            canonical = cluster["canonical_query"]
            similarity = score_jaccard(q_text, canonical)
            if similarity >= threshold:
                cluster["count"] += 1
                cluster["queries"].append(q_text)
                if record.timestamp:
                    if "last_query_timestamp" not in cluster or cluster["last_query_timestamp"] is None or record.timestamp > cluster["last_query_timestamp"]:
                        cluster["last_query_timestamp"] = record.timestamp
                found_cluster = True
                break
                
        if not found_cluster:
            clusters.append({
                "id": record.id,
                "canonical_query": q_text,
                "count": 1,
                "queries": [q_text],
                "last_query_timestamp": record.timestamp,
                "resolved_by_document_id": q_cluster.resolved_by_document_id if q_cluster else None,
                "resolved_at": q_cluster.resolved_at if q_cluster else None,
            })
            
    # Optionally, pick the shortest or most frequent within cluster as canonical
    # For now, let's keep the first one as canonical and remove 'queries' to save output size if not needed,
    # but returning it might be useful.
    
    clusters.sort(key=lambda x: x["count"], reverse=True)
    return clusters

def mark_cluster_handled(db: Session, cluster_id: int, document_id: int, last_query_timestamp: Optional[datetime] = None):
    from app.models.query_cluster import QueryCluster
    cluster = db.query(QueryCluster).filter(QueryCluster.id == cluster_id).first()
    if cluster:
        cluster.status = "handled"
        cluster.resolved_by_document_id = document_id
        cluster.resolved_at = datetime.utcnow()
        if last_query_timestamp is not None:
            cluster.last_resolved_query_timestamp = last_query_timestamp
        db.commit()
    return cluster
