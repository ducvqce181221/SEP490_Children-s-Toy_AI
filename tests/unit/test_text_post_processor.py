"""
tests/unit/test_text_post_processor.py
---------------------------------------
Unit tests for text_pipeline/post_processor.py.
"""

from __future__ import annotations

from app.schemas.moderation import ModerationDecision, TextPipelineResult
from app.application.moderation.business_rules import (
    PostProcessContext,
    apply_business_rules,
)


def _make_result(
    decision: ModerationDecision = ModerationDecision.APPROVED,
    confidence: float = 0.95,
    flags: list[str] | None = None,
) -> TextPipelineResult:
    return TextPipelineResult(
        decision=decision, confidence=confidence,
        category="clean", flags=flags or [], reason="Test result",
    )


class TestApplyBusinessRules:

    def test_low_confidence_escalates_to_manual(self):
        result = _make_result(confidence=0.50)
        ctx = PostProcessContext(recent_rejected_count=0)
        out = apply_business_rules(result, ctx)
        assert out.decision == ModerationDecision.MANUAL_REVIEW
        assert any("low_confidence" in f for f in out.flags)

    def test_confidence_at_threshold_passes(self):
        result = _make_result(confidence=0.70)
        ctx = PostProcessContext(recent_rejected_count=0)
        out = apply_business_rules(result, ctx)
        assert out.decision == ModerationDecision.APPROVED

    def test_high_confidence_no_change(self):
        result = _make_result(confidence=0.99)
        ctx = PostProcessContext(recent_rejected_count=0)
        out = apply_business_rules(result, ctx)
        assert out.decision == ModerationDecision.APPROVED

    def test_health_concern_flag_escalates(self):
        result = _make_result(confidence=0.90, flags=["health_concern"])
        ctx = PostProcessContext(recent_rejected_count=0)
        out = apply_business_rules(result, ctx)
        assert out.decision == ModerationDecision.MANUAL_REVIEW
        assert any("health_concern" in f for f in out.flags)

    def test_health_concern_on_rejected_stays_rejected(self):
        result = _make_result(
            decision=ModerationDecision.REJECTED, confidence=0.90, flags=["health_concern"]
        )
        ctx = PostProcessContext(recent_rejected_count=0)
        out = apply_business_rules(result, ctx)
        assert out.decision == ModerationDecision.REJECTED

    def test_repeat_offender_escalates_approved(self):
        from app.configs.config import get_settings
        settings = get_settings()
        result = _make_result(confidence=0.90)
        ctx = PostProcessContext(
            recent_rejected_count=settings.account_rejected_review_max,
        )
        out = apply_business_rules(result, ctx)
        assert out.decision == ModerationDecision.MANUAL_REVIEW
        assert any("repeat_offender" in f for f in out.flags)

    def test_one_rejection_not_escalated(self):
        from app.configs.config import get_settings
        settings = get_settings()
        result = _make_result(confidence=0.90)
        ctx = PostProcessContext(
            recent_rejected_count=settings.account_rejected_review_max - 1,
        )
        out = apply_business_rules(result, ctx)
        assert out.decision == ModerationDecision.APPROVED

    def test_clean_review_unchanged(self):
        result = _make_result(confidence=0.95)
        ctx = PostProcessContext(recent_rejected_count=0)
        out = apply_business_rules(result, ctx)
        assert out.decision == ModerationDecision.APPROVED
        assert out is result

