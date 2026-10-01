'''Subsystem health endpoint.'''
from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.vector_store import get_vector_store

router = APIRouter(tags=["health"])


@router.get("/api/health/subsystems")
def subsystem_health(response: Response, session: Session = Depends(get_db)):
    """Check that the database and the vector store answer. Returns 503 if either does not."""
    try:
        session.execute(text("SELECT 1"))
        db = "healthy"
    except Exception:
        db = "unavailable"
    vector_store = "healthy" if get_vector_store().ping() else "unavailable"
    if "unavailable" in (db, vector_store):
        response.status_code = 503
    return {"db": db, "vector_store": vector_store}
