"""
app/worker/scheduler.py
-----------------------
APScheduler setup: polls DB every N seconds for Pending reviews (Option A).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.logging import get_logger
from app.features.moderation.blog_comment.jobs import (
    run_auto_reject_manual_review_timeout_job,
    run_auto_unlock_comment_accounts_job,
)
from app.worker.blog_comment_worker import run_blog_comment_moderation_batch
from app.worker.product_review_worker import run_moderation_batch

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None
_is_review_running: bool = False
_is_blog_comment_running: bool = False


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


async def _safe_run_blog_comment_batch() -> None:
    global _is_blog_comment_running
    if _is_blog_comment_running:
        logger.debug("Previous blog comment batch still running, skipping this cycle")
        return
    _is_blog_comment_running = True
    try:
        await run_blog_comment_moderation_batch()
    except Exception as exc:
        logger.error("Blog comment scheduler batch failed", error=str(exc), exc_info=True)
    finally:
        _is_blog_comment_running = False


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
    if settings.blog_comment_worker_enabled:
        scheduler.add_job(
            func=_safe_run_blog_comment_batch,
            trigger=IntervalTrigger(seconds=settings.blog_comment_poll_interval_seconds),
            id="blog_comment_moderation_poll",
            name="Blog Comment Moderation Poll Worker",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            func=run_auto_reject_manual_review_timeout_job,
            trigger=IntervalTrigger(hours=1),
            id="blog_comment_auto_reject_timeout",
            name="Blog Comment Auto Reject Timeout Job",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            func=run_auto_unlock_comment_accounts_job,
            trigger=IntervalTrigger(hours=1),
            id="blog_comment_auto_unlock_accounts",
            name="Blog Comment Auto Unlock Accounts Job",
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
