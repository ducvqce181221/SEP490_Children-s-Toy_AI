"""
app/application/moderation/business_rules.py
--------------------------------------------
Post-process Business Rules for review moderation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.schemas.moderation import ModerationDecision, TextPipelineResult

logger = get_logger(__name__)


@dataclass
class PostProcessContext:
    """
    Extra context needed to apply business rules.
    Populated by the repository before calling post_processor.
    """
    recent_rejected_count: int    # Rejected reviews by this account in last N days
    product_created_at: datetime | None = None  # UTC datetime when the product was created


def apply_business_rules(
    result: TextPipelineResult,
    context: PostProcessContext,
) -> TextPipelineResult:
    """
    Apply post-processing business rules that can override the LLM decision.
    """
    settings = get_settings()
    overrides: list[str] = []
    override_descriptions: list[str] = []
    new_decision = result.decision

    # Rule 1: Low confidence → escalate APPROVED/ambiguous to MANUAL_REVIEW
    if result.confidence < settings.llm_confidence_threshold:
        if new_decision == ModerationDecision.APPROVED:
            new_decision = ModerationDecision.MANUAL_REVIEW
            overrides.append(
                f"low_confidence:{result.confidence:.2f}<{settings.llm_confidence_threshold}"
            )
            override_descriptions.append("AI confidence is low")

    # Rule 2: health_concern flag → escalate APPROVED to MANUAL_REVIEW (child safety)
    if "health_concern" in result.flags:
        if new_decision == ModerationDecision.APPROVED:
            new_decision = ModerationDecision.MANUAL_REVIEW
            overrides.append("health_concern_flag")
            override_descriptions.append("Suspected child health/safety concern")

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
            f"Account has {context.recent_rejected_count} recently rejected reviews"
        )

    if not overrides:
        return result

    updated_flags = result.flags + [f"override:{o}" for o in overrides]
    override_reason = "; ".join(override_descriptions)
    reason = f"Content does not directly violate policy but requires manual review: {override_reason}"

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
