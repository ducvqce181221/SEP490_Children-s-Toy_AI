"""
app/api/router.py
-----------------
FastAPI router for moderation and blog generation endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.schemas.moderation import BlogCommentTargetType
from app.application.moderation.product_review import ModerationOrchestrator
from app.application.moderation.blog_comment import BlogCommentModerationService
from app.schemas.blog_content import (
    BlogContentGenerateRequest,
    BlogContentGenerateEndpointResponse,
    BlogContentBlockedResponse,
    BlogContentGenerateResponse,
)
from app.application.blog_generation.service import (
    BlogContentGenerationError,
    generate_blog_content,
)

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
    orchestrator = ModerationOrchestrator()
    try:
        counts = await orchestrator.get_moderation_stats()
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
        orchestrator = ModerationOrchestrator()
        processed = await orchestrator.moderate_pending_batch()
    except Exception as exc:
        logger.error("Manual trigger failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Moderation batch failed: {exc}")
    return TriggerResponse(message="Moderation batch complete", processed=processed)


@router.get("/blog-comments/stats", response_model=BlogCommentModerationStatsResponse)
async def get_blog_comment_moderation_stats() -> BlogCommentModerationStatsResponse:
    service = BlogCommentModerationService()
    try:
        counts = await service.get_comment_moderation_stats()
    except Exception as exc:
        logger.error("Failed to fetch blog comment moderation stats", error=str(exc))
        raise HTTPException(status_code=500, detail="Database error")

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
    service = BlogCommentModerationService()
    accepted, final_status = await service.moderate_single_comment(
        target_type=payload.targetType,
        target_id=payload.targetId,
    )
    return ModerateOneResponse(accepted=accepted, final_status=final_status)


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
