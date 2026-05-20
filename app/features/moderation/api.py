"""
app/features/moderation/api.py
-------------------------------
FastAPI router for moderation-related endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.database import get_connection, get_cursor
from app.core.logging import get_logger
from app.worker.moderation_worker import run_moderation_batch

logger = get_logger(__name__)
router = APIRouter(prefix="/moderation", tags=["moderation"])


async def verify_internal_key(x_internal_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if x_internal_key != settings.internal_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Internal-Key")


class ModerationStatsResponse(BaseModel):
    pending: int
    processing: int
    approved: int
    rejected: int
    manual_review: int
    total: int


class TriggerResponse(BaseModel):
    message: str
    processed: int


@router.get("/stats", response_model=ModerationStatsResponse)
async def get_moderation_stats() -> ModerationStatsResponse:
    sql = """
        SELECT [ModerationStatus], COUNT(*) AS cnt
        FROM [dbo].[ReviewProducts]
        WHERE [IsDeleted] = 0
        GROUP BY [ModerationStatus]
    """
    counts: dict[str, int] = {
        "Pending": 0, "Processing": 0, "Approved": 0, "Rejected": 0, "ManualReview": 0,
    }
    try:
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        for row in rows:
            status, count = row[0], row[1]
            if status in counts:
                counts[status] = count
    except Exception as exc:
        logger.error("Failed to fetch moderation stats", error=str(exc))
        raise HTTPException(status_code=500, detail="Database error")

    total = sum(counts.values())
    return ModerationStatsResponse(
        pending=counts["Pending"], processing=counts["Processing"],
        approved=counts["Approved"], rejected=counts["Rejected"],
        manual_review=counts["ManualReview"], total=total,
    )


@router.post("/trigger", response_model=TriggerResponse, dependencies=[Depends(verify_internal_key)])
async def trigger_moderation() -> TriggerResponse:
    logger.info("Manual moderation trigger received")
    try:
        processed = await run_moderation_batch()
    except Exception as exc:
        logger.error("Manual trigger failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Moderation batch failed: {exc}")
    return TriggerResponse(message="Moderation batch complete", processed=processed)
