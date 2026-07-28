"""
app/main.py
-----------
FastAPI application entry point.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.configs.config import get_settings
from app.database.connection import close_db_pool, init_db_pool
from app.core.logging import get_logger, setup_logging
from app.api.router import router as moderation_router

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger(__name__)

settings.setup_google_credentials_env()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting AI Moderation Service", env=settings.app_env)

    await init_db_pool()
    logger.info("Worker mode: DIRECT_API (Internal scheduler removed, operating as stateless REST API microservice)")

    yield

    await close_db_pool()
    logger.info("AI Moderation Service shutdown complete")


app = FastAPI(
    title="SEP490 AI Moderation Sidecar",
    description="Sidecar service for automated review moderation using Groq LLM and Google Cloud Vision.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
)

app.include_router(moderation_router)


@app.get("/health", tags=["health"])
async def health_check() -> JSONResponse:
    return JSONResponse(
        content={"status": "ok", "service": "ai-moderation-sidecar", "version": "1.0.0"},
        status_code=200,
    )

if __name__ == "__main__":
    import uvicorn
    # Note: use "app.main:app" instead of "main:app" for uvicorn to resolve package structure correctly
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
