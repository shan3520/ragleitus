import logging
from fastapi import FastAPI
from src.core.config import settings
from src.core.logging import setup_logging
from src.api.health import router as health_router
from src.api.provider_keys import router as provider_keys_router

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
    
    logger = logging.getLogger(__name__)
    logger.info("Application starting up")
    
    return app

app = create_app()
