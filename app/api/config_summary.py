'''Config summary endpoint.'''
from fastapi import APIRouter, Depends
from app.api.deps import get_current_user
from app.core.config import settings

router = APIRouter(tags=["config"], dependencies=[Depends(get_current_user)])

@router.get("/api/config/summary")
def config_summary():
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "chunk_window_size": settings.chunk_window_size,
    }
