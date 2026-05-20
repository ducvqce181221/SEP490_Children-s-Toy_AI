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

from app.core.config import get_settings
from app.core.database import close_db_pool, init_db_pool
from app.core.logging import get_logger, setup_logging
from app.features.moderation.api import router as moderation_router
from app.worker.scheduler import start_scheduler, stop_scheduler

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger(__name__)

settings.setup_google_credentials_env()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting AI Moderation Sidecar", env=settings.app_env)

    await init_db_pool()

    if settings.trigger_mode == "POLL":
        start_scheduler()
        logger.info("Worker mode: POLL", interval=settings.poll_interval_seconds)
    else:
        logger.info("Worker mode: OUTBOX (not yet implemented)")

    yield

    stop_scheduler()
    await close_db_pool()
    logger.info("AI Moderation Sidecar shutdown complete")


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
    # Lưu ý: dùng "app.main:app" thay vì "main:app" để uvicorn hiểu đúng cấu trúc package
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
