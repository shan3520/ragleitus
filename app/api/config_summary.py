'''Config summary endpoint.'''
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(tags=["config"])

@router.get("/api/config/summary")
def config_summary():
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "chunk_window_size": settings.chunk_window_size,
    }
