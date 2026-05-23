"""
app/worker/blog_comment_worker.py
---------------------------------
Worker for processing pending blog comments.
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.features.moderation.blog_comment.repository import BlogCommentModerationRepository
from app.features.moderation.blog_comment.service import BlogCommentModerationService

logger = get_logger(__name__)


async def run_blog_comment_moderation_batch() -> int:
    settings = get_settings()
    repo = BlogCommentModerationRepository()
    service = BlogCommentModerationService()

    claimed = await repo.claim_pending_comments(
        batch_size=settings.blog_comment_batch_size,
        retry_interval_minutes=settings.blog_comment_retry_interval_minutes,
    )
    if not claimed:
        logger.debug("No pending blog comments for moderation")
        return 0

    semaphore = asyncio.Semaphore(settings.blog_comment_max_concurrent)

    async def _run_one(record) -> None:
        async with semaphore:
            await service.moderate_one(record)

    await asyncio.gather(*[_run_one(record) for record in claimed], return_exceptions=True)
    logger.info("Blog comment moderation batch complete", processed=len(claimed))
    return len(claimed)

