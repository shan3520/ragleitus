from fastapi import FastAPI
from src.core.config import settings

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc"
    )
    return app

app = create_app()
