import logging
from fastapi import FastAPI
from app.core.config import settings
from app.core.logging import setup_logging
from app.api.health import router as health_router
from app.api.provider_keys import router as provider_keys_router
from app.api.auth import router as auth_router

def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title=settings.app_name,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc"
    )
    
    app.include_router(health_router)
    app.include_router(provider_keys_router)
    app.include_router(auth_router)
    
    logger = logging.getLogger(__name__)
    logger.info("Application starting up")
    
    return app

app = create_app()
