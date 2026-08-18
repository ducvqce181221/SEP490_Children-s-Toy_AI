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


class ModerateProductReviewRequest(BaseModel):
    reviewId: int


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

# 1. Endpoint tiếp nhận request kiểm duyệt 1 review sản phẩm
@router.post(
    "/product-reviews/moderate-one",
    response_model=ModerateOneResponse,
    dependencies=[Depends(verify_internal_key)], # Check mật khẩu X-Internal-Key giữa C# và Python
)
async def moderate_one_product_review(payload: ModerateProductReviewRequest) -> ModerateOneResponse:
    logger.info("Moderate single product review request received", review_id=payload.reviewId)
    orchestrator = ModerationOrchestrator()
    # 2. Gọi hàm kiểm duyệt chính và trả về kết quả cho C# Backend
    accepted, final_status = await orchestrator.moderate_single_review(payload.reviewId)
    return ModerateOneResponse(accepted=accepted, final_status=final_status)



# --- API CHỨC NĂNG AI CHO BLOG ---

# 1. API Thống kê số lượng kiểm duyệt bình luận Blog (Stats)
@router.get("/blog-comments/stats", response_model=BlogCommentModerationStatsResponse)
async def get_blog_comment_moderation_stats() -> BlogCommentModerationStatsResponse:
    """Lấy số lượng bình luận Blog theo từng trạng thái (Pending, Processing, Approved, Rejected, ManualReview, Failed)."""
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


# 2. API Yêu cầu kiểm duyệt tức thì 1 Bình luận / Phản hồi Blog từ C# Backend
@router.post(
    "/blog-comments/moderate-one",
    response_model=ModerateOneResponse,
    dependencies=[Depends(verify_internal_key)], # Xác thực X-Internal-Key
)
async def moderate_one_blog_comment(payload: ModerateOneRequest) -> ModerateOneResponse:
    """Tiếp nhận yêu cầu kiểm duyệt 1 bình luận hoặc phản hồi Blog từ Backend và trả về kết quả thành công/trạng thái."""
    service = BlogCommentModerationService()
    accepted, final_status = await service.moderate_single_comment(
        target_type=payload.targetType,
        target_id=payload.targetId,
    )
    return ModerateOneResponse(accepted=accepted, final_status=final_status)


# 3. API Yêu cầu sinh nội dung bài viết Blog tự động bằng AI (Blog Generation Endpoint)
@router.post(
    "/blog-content/generate",
    response_model=BlogContentGenerateEndpointResponse,
    dependencies=[Depends(verify_internal_key)], # Xác thực X-Internal-Key
)
async def generate_blog_content_endpoint(payload: BlogContentGenerateRequest) -> BlogContentGenerateEndpointResponse:
    """
    Tiếp nhận yêu cầu sinh nội dung bài viết Blog bằng AI (Generate / Improve / Rewrite).
    Nếu yêu cầu vi phạm quy tắc an toàn/chủ đề, trả về response bị chặn (BlogContentBlockedResponse) kèm gợi ý.
    Nếu thành công, trả về tiêu đề và nội dung bài viết chuẩn định dạng HTML (BlogContentGenerateResponse).
    """
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

