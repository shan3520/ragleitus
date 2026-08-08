from fastapi import APIRouter, Depends
from app.core.health import HealthService, HealthRepository
from app.core.config import settings

router = APIRouter()

def get_health_service() -> HealthService:
    repository = HealthRepository()
    return HealthService(repository)

@router.get("/health")
def health_check(service: HealthService = Depends(get_health_service)):
    return service.get_health_status()

@router.get("/version")
def get_version():
    return {"app_name": settings.PROJECT_NAME, "version": settings.VERSION}
