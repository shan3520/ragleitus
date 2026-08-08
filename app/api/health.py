from fastapi import APIRouter, Depends
from app.core.health import HealthService, HealthRepository

router = APIRouter()

def get_health_service() -> HealthService:
    repository = HealthRepository()
    return HealthService(repository)

@router.get("/health")
def health_check(service: HealthService = Depends(get_health_service)):
    return service.get_health_status()
