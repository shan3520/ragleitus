'''
Hybrid search score merger.
'''
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from app.services.document_search import _log_search, _log_unmatched_search

def combine_scores(
    keyword_scores: dict[str, float],
    vector_scores: dict[str, float],
    alpha: float = 0.5,
    query: str | None = None,
    background_tasks: BackgroundTasks | None = None,
    session: Session | None = None,
) -> dict[str, float]:
    all_keys = set(keyword_scores.keys()) | set(vector_scores.keys())
    combined = {}
    for key in all_keys:
        kw = keyword_scores.get(key, 0.0)
        vec = vector_scores.get(key, 0.0)
        combined[key] = round(alpha * kw + (1.0 - alpha) * vec, 4)
        
    if background_tasks and session and query is not None:
        if not combined:
            background_tasks.add_task(_log_unmatched_search, session, query)
        else:
            try:
                matched_ids = [int(k) for k in combined.keys()]
                background_tasks.add_task(_log_search, session, query, matched_ids)
            except ValueError:
                pass

    return combined
