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
from app.features.moderation.blog_comment.jobs import (
    run_auto_reject_manual_review_timeout_job,
    run_auto_unlock_comment_accounts_job,
)
from app.features.moderation.blog_comment.repository import BlogCommentModerationRepository
from app.features.moderation.blog_comment.schemas import BlogCommentTargetType
from app.features.moderation.blog_comment.service import BlogCommentModerationService
from app.features.moderation.blog_comment.worker import run_blog_comment_moderation_batch
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


class BlogCommentModerationStatsResponse(BaseModel):
    pending: int
    processing: int
    approved: int
    rejected: int
    manual_review: int
    failed: int
    total: int


class ModerateOneRequest(BaseModel):
    targetType: BlogCommentTargetType
    targetId: int


class ModerateOneResponse(BaseModel):
    accepted: bool
    final_status: str | None = None


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


@router.get("/blog-comments/stats", response_model=BlogCommentModerationStatsResponse)
async def get_blog_comment_moderation_stats() -> BlogCommentModerationStatsResponse:
    counts: dict[str, int] = {
        "Pending": 0,
        "Processing": 0,
        "Approved": 0,
        "Rejected": 0,
        "ManualReview": 0,
        "Failed": 0,
    }
    sql = """
        SELECT [ModerationStatus], COUNT(*) AS cnt
        FROM (
            SELECT [ModerationStatus] FROM [dbo].[ReviewBlogs] WHERE [IsDeleted] = 0
            UNION ALL
            SELECT [ModerationStatus] FROM [dbo].[ReviewBlogReplies] WHERE [IsDeleted] = 0
        ) x
        GROUP BY [ModerationStatus]
    """
    async with get_connection() as conn:
        async with get_cursor(conn) as cur:
            await cur.execute(sql)
            rows = await cur.fetchall()
    for row in rows:
        status = row[0]
        if status in counts:
            counts[status] = int(row[1])
    total = sum(counts.values())
    return BlogCommentModerationStatsResponse(
        pending=counts["Pending"],
        processing=counts["Processing"],
        approved=counts["Approved"],
        rejected=counts["Rejected"],
        manual_review=counts["ManualReview"],
        failed=counts["Failed"],
        total=total,
    )


@router.post("/blog-comments/trigger", response_model=TriggerResponse, dependencies=[Depends(verify_internal_key)])
async def trigger_blog_comment_moderation() -> TriggerResponse:
    processed = await run_blog_comment_moderation_batch()
    return TriggerResponse(message="Blog comment moderation batch complete", processed=processed)


@router.post("/blog-comments/jobs/manual-review-timeout", response_model=TriggerResponse, dependencies=[Depends(verify_internal_key)])
async def trigger_manual_review_timeout_job() -> TriggerResponse:
    processed = await run_auto_reject_manual_review_timeout_job()
    return TriggerResponse(message="Manual review timeout job complete", processed=processed)


@router.post("/blog-comments/jobs/unlock-accounts", response_model=TriggerResponse, dependencies=[Depends(verify_internal_key)])
async def trigger_unlock_accounts_job() -> TriggerResponse:
    processed = await run_auto_unlock_comment_accounts_job()
    return TriggerResponse(message="Unlock comment accounts job complete", processed=processed)


@router.post(
    "/blog-comments/moderate-one",
    response_model=ModerateOneResponse,
    dependencies=[Depends(verify_internal_key)],
)
async def moderate_one_blog_comment(payload: ModerateOneRequest) -> ModerateOneResponse:
    repo = BlogCommentModerationRepository()
    service = BlogCommentModerationService()

    claimed = await repo.claim_target_for_immediate_moderation(
        target_type=payload.targetType,
        target_id=payload.targetId,
    )
    if claimed is None:
        status = await repo.get_target_status(
            target_type=payload.targetType,
            target_id=payload.targetId,
        )
        return ModerateOneResponse(accepted=False, final_status=status)

    await service.moderate_one(claimed)
    final_status = await repo.get_target_status(
        target_type=payload.targetType,
        target_id=payload.targetId,
    )
    return ModerateOneResponse(accepted=True, final_status=final_status)
