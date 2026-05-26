"""
app/worker/product_review_worker.py
--------------------------------
Core worker: fetches Pending reviews from DB and runs moderation pipeline.
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.features.moderation.product_review.repository import ModerationRepository
from app.features.moderation.product_review.service import ModerationOrchestrator

logger = get_logger(__name__)

_BATCH_SIZE = 20


async def run_moderation_batch() -> int:
    settings = get_settings()
    repo = ModerationRepository()
    orchestrator = ModerationOrchestrator()

    reviews = await repo.fetch_pending_reviews(batch_size=_BATCH_SIZE)

    if not reviews:
        logger.debug("No pending reviews found in this cycle")
        return 0

    logger.info("Processing batch", count=len(reviews))

    semaphore = asyncio.Semaphore(settings.max_concurrent_reviews)

    async def _process_one(review):
        async with semaphore:
            await orchestrator.moderate_review(review)

    await asyncio.gather(*[_process_one(r) for r in reviews], return_exceptions=True)

    logger.info("Batch complete", processed=len(reviews))
    return len(reviews)
