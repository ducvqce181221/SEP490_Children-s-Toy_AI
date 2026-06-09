"""
app/worker/scheduler.py
-----------------------
APScheduler setup: polls DB every N seconds for Pending reviews (Option A).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.worker.product_review_worker import run_moderation_batch

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None
_is_review_running: bool = False


async def _safe_run_batch() -> None:
    global _is_review_running
    if _is_review_running:
        logger.debug("Previous product review batch still running, skipping this cycle")
        return
    _is_review_running = True
    try:
        await run_moderation_batch()
    except Exception as exc:
        logger.error("Scheduler batch failed", error=str(exc), exc_info=True)
    finally:
        _is_review_running = False


def create_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        func=_safe_run_batch,
        trigger=IntervalTrigger(seconds=settings.poll_interval_seconds),
        id="moderation_poll",
        name="Moderation Poll Worker",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _scheduler = create_scheduler()
    _scheduler.start()
    settings = get_settings()
    logger.info("Moderation scheduler started", interval_seconds=settings.poll_interval_seconds)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Moderation scheduler stopped")
    _scheduler = None
