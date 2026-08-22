'''
Hybrid search score merger.
'''
import time
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
    skip: int = 0,
    limit: int = 20,
) -> dict:
    start_time = time.perf_counter()

    all_keys = set(keyword_scores.keys()) | set(vector_scores.keys())
    combined = {}
    for key in all_keys:
        kw = keyword_scores.get(key, 0.0)
        vec = vector_scores.get(key, 0.0)
        combined[key] = round(alpha * kw + (1.0 - alpha) * vec, 4)

    if background_tasks and session and query is not None:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        if not combined:
            background_tasks.add_task(_log_unmatched_search, session, query, duration_ms=duration_ms)
        else:
            try:
                matched_ids = [int(k) for k in combined.keys()]
                background_tasks.add_task(_log_search, session, query, matched_ids, duration_ms=duration_ms)
            except ValueError:
                pass

    # Total counts every merged result before any slicing so clients can size
    # the result set independently of the requested page.
    total = len(combined)
    ordered = sorted(combined.items(), key=lambda kv: (-kv[1], str(kv[0])))
    items = ordered[skip : skip + limit]
    return {"total": total, "items": items}
