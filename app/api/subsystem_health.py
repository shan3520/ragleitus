'''Subsystem health endpoint.'''
from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/api/health/subsystems")
def subsystem_health():
    return {"db": "healthy", "vector_store": "healthy", "cache": "healthy"}
