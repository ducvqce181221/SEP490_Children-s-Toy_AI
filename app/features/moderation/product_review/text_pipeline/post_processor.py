"""
app/features/moderation/product_review/text_pipeline/post_processor.py
----------------------------------------------------------------------
Bước 3 của text pipeline: Post-process Business Rules.

Override quyết định của AI nếu:
  1. confidence < 0.70 → ép về MANUAL_REVIEW
  2. flags chứa "health_concern" → ép về MANUAL_REVIEW
  3. Tài khoản có >= 2 review bị Rejected trong 30 ngày gần nhất
     → hạ APPROVED xuống MANUAL_REVIEW
  4. Sản phẩm được tạo trong vòng 7 ngày gần nhất
     → hạ APPROVED xuống MANUAL_REVIEW
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.logging import get_logger
from app.features.moderation.schemas import ModerationDecision, TextPipelineResult

logger = get_logger(__name__)


@dataclass
class PostProcessContext:
    """
    Extra context needed to apply business rules.
    Populated by the repository before calling post_processor.
    """
    recent_rejected_count: int    # Rejected reviews by this account in last N days
    product_created_at: datetime  # UTC datetime when the product was created


def apply_business_rules(
    result: TextPipelineResult,
    context: PostProcessContext,
) -> TextPipelineResult:
    """
    Apply post-processing business rules that can override the LLM decision.

    Args:
        result: Result from LLM classifier (Bước 2).
        context: Account and product metadata.

    Returns:
        Potentially modified TextPipelineResult (decision may be escalated).
    """
    settings = get_settings()
    overrides: list[str] = []
    override_descriptions: list[str] = []
    new_decision = result.decision

    # Rule 1: Low confidence → escalate APPROVED/ambiguous to MANUAL_REVIEW
    # (do NOT downgrade REJECTED — REJECTED is more severe than MANUAL_REVIEW)
    if result.confidence < settings.llm_confidence_threshold:
        if new_decision == ModerationDecision.APPROVED:
            new_decision = ModerationDecision.MANUAL_REVIEW
            overrides.append(
                f"low_confidence:{result.confidence:.2f}<{settings.llm_confidence_threshold}"
            )
            override_descriptions.append("Độ tin cậy của AI thấp")

    # Rule 2: health_concern flag → escalate APPROVED to MANUAL_REVIEW (child safety)
    # (do NOT downgrade REJECTED — a rejected review with health concern stays rejected)
    if "health_concern" in result.flags:
        if new_decision == ModerationDecision.APPROVED:
            new_decision = ModerationDecision.MANUAL_REVIEW
            overrides.append("health_concern_flag")
            override_descriptions.append("Nghi vấn lo ngại về sức khỏe/an toàn trẻ em")

    # Rule 3: Repeat offender → downgrade APPROVED to MANUAL_REVIEW
    if (
        result.decision == ModerationDecision.APPROVED
        and context.recent_rejected_count >= settings.account_rejected_review_max
    ):
        new_decision = ModerationDecision.MANUAL_REVIEW
        overrides.append(
            f"repeat_offender:{context.recent_rejected_count}_rejected_in_{settings.account_rejected_review_days}d"
        )
        override_descriptions.append(
            f"Tài khoản có {context.recent_rejected_count} đánh giá bị từ chối gần đây"
        )

    # Rule 4: New product (created < N days ago) → downgrade APPROVED to MANUAL_REVIEW
    now_utc = datetime.now(tz=timezone.utc)
    product_age_days = (now_utc - context.product_created_at.replace(tzinfo=timezone.utc)).days
    if (
        result.decision == ModerationDecision.APPROVED
        and product_age_days < settings.new_product_days
    ):
        new_decision = ModerationDecision.MANUAL_REVIEW
        overrides.append(f"new_product:{product_age_days}d_old")
        override_descriptions.append("Sản phẩm mới đăng bán cần duyệt kỹ")

    if not overrides:
        return result

    # Build updated result with override flags
    updated_flags = result.flags + [f"override:{o}" for o in overrides]
    override_reason = "; ".join(override_descriptions)
    reason = f"Nội dung không vi phạm trực tiếp nhưng cần duyệt thủ công: {override_reason}"

    logger.info(
        "Post-processor overrode LLM decision",
        original=result.decision,
        new=new_decision,
        overrides=overrides,
    )

    return TextPipelineResult(
        decision=new_decision,
        confidence=result.confidence,
        category=result.category,
        flags=updated_flags,
        reason=reason[:500],  # DB column limit NVARCHAR(500)
        decided_by="post_processor",
        raw_llm_result=result.raw_llm_result,
    )
