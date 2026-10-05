import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import RequestIDMiddleware, RateLimitMiddleware
from app.services import ingestion
from app.api.health import router as health_router
from app.api.provider_keys import router as provider_keys_router
from app.api.auth import router as auth_router
from app.api.stats import router as stats_router
from app.api.search import router as search_router
from app.api.evaluations import router as evaluations_router
from app.api.documents import router as documents_router
from app.api.cleaning import router as cleaning_router
from app.api.chunking import router as chunking_router
from app.api.export import router as export_router
from app.api.batch_upload import router as batch_router
from app.api.subsystem_health import router as subsystem_router
from app.api.experiment_reports import router as reports_router
from app.api.config_summary import router as config_summary_router
from app.api.groups import router as groups_router
from app.api.unanswered_queries import router as unanswered_queries_router
from app.api.feedback import router as feedback_router
from app.api.history import router as history_router
from app.api.telemetry import router as telemetry_router
from app.api.chat import router as chat_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle.

    The schema is managed by Alembic; run `alembic upgrade head` before
    starting the application.
    """
    logger.info(
        "Application starting",
        extra={"version": settings.VERSION, "project": settings.PROJECT_NAME},
    )
    if settings.task_queue == "inline":
        # In-process indexing jobs die with the process; pick up any a restart
        # interrupted. (With Celery, workers do this when they start.)
        try:
            ingestion.requeue_stalled()
        except Exception:
            logger.exception("Could not re-queue stalled documents")
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request tracing and rate limiting middleware
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RateLimitMiddleware)
    # Added last, so it runs first: believe X-Forwarded-For / X-Forwarded-Proto
    # only from TRUSTED_PROXIES (empty: from nobody). Run uvicorn with
    # --no-proxy-headers so its own default trust of 127.0.0.1 does not apply.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.trusted_proxies)

    app.include_router(health_router)
    app.include_router(provider_keys_router)
    app.include_router(auth_router)
    app.include_router(stats_router)
    app.include_router(search_router)
    app.include_router(evaluations_router)
    app.include_router(documents_router)
    app.include_router(cleaning_router)
    app.include_router(chunking_router)
    app.include_router(export_router)
    app.include_router(batch_router)
    app.include_router(subsystem_router)
    app.include_router(reports_router)
    app.include_router(config_summary_router)
    app.include_router(groups_router, prefix="/api/groups")
    app.include_router(unanswered_queries_router)
    app.include_router(feedback_router)
    app.include_router(history_router)
    app.include_router(telemetry_router)
    app.include_router(chat_router)

    return app

app = create_app()
