import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import RequestIDMiddleware, RateLimitMiddleware
from app.db.database import Base, engine
from app.api.health import router as health_router
from app.api.provider_keys import router as provider_keys_router
from app.api.auth import router as auth_router
from app.api.stats import router as stats_router
from app.api.search import router as search_router
from app.api.evaluations import router as evaluations_router
from app.api.documents import router as documents_router
from app.api.cleaning import router as cleaning_router
from app.api.chunking import router as chunking_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    Base.metadata.create_all(bind=engine)
    logger.info(
        "Application starting",
        extra={"version": settings.VERSION, "project": settings.PROJECT_NAME},
    )
    yield
    logger.info("Application shutting down")


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS — allow the frontend origin in production, everything in dev
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else ["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request tracing and rate limiting middleware
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RateLimitMiddleware)

    app.include_router(health_router)
    app.include_router(provider_keys_router)
    app.include_router(auth_router)
    app.include_router(stats_router)
    app.include_router(search_router)
    app.include_router(evaluations_router)
    app.include_router(documents_router)
    app.include_router(cleaning_router)
    app.include_router(chunking_router)

    return app

app = create_app()
