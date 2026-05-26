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
from app.features.moderation.blog_comment.repository import BlogCommentModerationRepository
from app.features.moderation.schemas import BlogCommentTargetType
from app.features.moderation.blog_comment.service import BlogCommentModerationService
from app.features.blog_content.schemas import (
    BlogContentGenerateRequest,
    BlogContentGenerateEndpointResponse,
    BlogContentBlockedResponse,
    BlogContentGenerateResponse,
)
from app.features.blog_content.service import (
    BlogContentGenerationError,
    generate_blog_content,
)
from app.worker.product_review_worker import run_moderation_batch

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


@router.post(
    "/blog-content/generate",
    response_model=BlogContentGenerateEndpointResponse,
    dependencies=[Depends(verify_internal_key)],
)
async def generate_blog_content_endpoint(payload: BlogContentGenerateRequest) -> BlogContentGenerateEndpointResponse:
    logger.info(
        "Received blog content generation request",
        action=payload.action,
        title_len=len(payload.title or ""),
        prompt_len=len(payload.promptStructure or ""),
        category_id=payload.defaultCategoryId,
    )
    try:
        generated = await generate_blog_content(
            action=payload.action,
            title=payload.title,
            description=payload.description,
            prompt_structure=payload.promptStructure,
            tone=payload.defaultTone,
            category_id=payload.defaultCategoryId,
            source_content=payload.sourceContent,
        )
        if isinstance(generated, dict) and generated.get("status") == "blocked":
            logger.info(
                "Blog content blocked",
                violation_type=generated.get("violation_type"),
                violated_keyword=generated.get("violated_keyword"),
            )
            return BlogContentBlockedResponse.model_validate(generated)

        title, content = generated
        logger.info(
            "Blog content generation completed",
            title_len=len(title or ""),
            content_len=len(content or ""),
        )
        return BlogContentGenerateResponse(title=title, content=content)
    except BlogContentGenerationError as exc:
        logger.warning("Blog content generation failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
