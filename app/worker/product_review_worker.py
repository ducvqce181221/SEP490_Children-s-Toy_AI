"""
app/worker/product_review_worker.py
--------------------------------
Core worker: fetches Pending reviews from DB and runs moderation pipeline.
"""

from __future__ import annotations

from app.application.moderation.product_review import ModerationOrchestrator

_BATCH_SIZE = 20


async def run_moderation_batch() -> int:
    orchestrator = ModerationOrchestrator()
    return await orchestrator.moderate_pending_batch(batch_size=_BATCH_SIZE)
