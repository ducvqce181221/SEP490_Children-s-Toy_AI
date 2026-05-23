from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.features.moderation.blog_comment.reason_mapper import (
    AI_UNAVAILABLE_REASON,
    map_ai_category_to_reason_content,
)
from app.features.moderation.blog_comment.repository import BlogCommentModerationRepository
from app.features.moderation.blog_comment.retry_policy import BlogCommentRetryPolicy
from app.features.moderation.schemas import (
    BlogCommentRecord,
    BlogCommentTargetType,
    ModerationDecision,
    ModerationStatus,
    TextPipelineResult,
)
from app.features.moderation.blog_comment.violation_service import BlogCommentViolationService
from app.features.moderation.product_review.text_pipeline.prefilter import run_prefilter
from app.llm.client import get_blog_deepseek_client
from app.utils.text_utils import has_hard_profanity

logger = get_logger(__name__)

_FORCE_REJECT_CATEGORIES: set[str] = {
    "offensive",
    "profanity_mild",
    "abusive",
    "discriminatory",
    "harassment",
    "bullying",
    "spam",
    "ads",
    "link_spam",
    "competitor_ad",
    "sexual",
    "adult",
    "child_unsafe",
    "violent",
    "threat",
    "privacy",
    "doxxing",
}

_FORCE_REJECT_FLAGS: tuple[str, ...] = (
    "offensive",
    "profanity",
    "abusive",
    "discriminatory",
    "harassment",
    "bullying",
    "spam",
    "link",
    "url",
    "sexual",
    "adult",
    "child_unsafe",
    "violent",
    "threat",
    "privacy",
    "doxx",
)

_VIOLATION_REASON_TOKENS: tuple[str, ...] = (
    "profanity",
    "offensive",
    "abusive",
    "toxic",
    "vulgar",
    "insult",
    "harass",
    "hate",
    "sexual",
    "violent",
)


class BlogCommentModerationService:
    def __init__(self) -> None:
        self._repo = BlogCommentModerationRepository()
        self._violation = BlogCommentViolationService()
        self._retry_policy = BlogCommentRetryPolicy()
        self._settings = get_settings()

    async def moderate_one(self, record: BlogCommentRecord) -> None:
        try:
            ai_result = await self._classify_comment(record.comment or "")
        except Exception as exc:
            logger.error(
                "Blog comment moderation AI error",
                target_type=record.target_type.value,
                target_id=record.target_id,
                error=str(exc),
            )
            await self._handle_ai_error(record, str(exc))
            return

        if ai_result.decision == ModerationDecision.APPROVED:
            await self._approve(record, ai_result)
            return
        if ai_result.decision == ModerationDecision.MANUAL_REVIEW:
            await self._send_to_manual_review(record, ai_result)
            return
        await self._reject(record, ai_result)

    async def _classify_comment(self, comment: str) -> TextPipelineResult:
        # 1. Run local prefilter rules
        prefilter = run_prefilter(comment or "")
        if prefilter.rejected:
            logger.info("Blog comment prefilter rejected", reason=prefilter.reason)
            return TextPipelineResult(
                decision=ModerationDecision.REJECTED,
                category="spam",
                confidence=1.0,
                reason=prefilter.reason,
                flags=["rule_prefilter_reject"],
                decided_by="prefilter",
                raw_llm_result={
                    "decision": "REJECTED",
                    "confidence": 1.0,
                    "category": "spam",
                    "flags": ["rule_prefilter_reject"],
                    "reason": prefilter.reason,
                },
            )

        # 2. Run local hard profanity check
        if has_hard_profanity(comment):
            logger.info("Blog comment hard profanity rejected", comment=comment)
            return TextPipelineResult(
                decision=ModerationDecision.REJECTED,
                category="offensive",
                confidence=1.0,
                reason="Chứa từ ngữ thô tục cực đoan (chặn tự động)",
                flags=["rule_hard_profanity_reject"],
                decided_by="prefilter_profanity",
                raw_llm_result={
                    "decision": "REJECTED",
                    "confidence": 1.0,
                    "category": "offensive",
                    "flags": ["rule_hard_profanity_reject"],
                    "reason": "Chứa từ ngữ thô tục cực đoan (chặn tự động)",
                },
            )

        # 3. Call DeepSeek LLM classifier
        llm_data = await get_blog_deepseek_client().classify_text(
            comment=comment,
            content_type="comment",
            rating=None,
        )
        decision = self._to_decision(str(llm_data.get("decision", "MANUAL_REVIEW")))
        confidence = float(llm_data.get("confidence", 0.0))
        flags = [str(x) for x in llm_data.get("flags", [])]
        reason = str(llm_data.get("reason", ""))

        # Confidence safeguard (Override decision to MANUAL_REVIEW if confidence is low)
        if decision == ModerationDecision.APPROVED and confidence < self._settings.llm_confidence_threshold:
            decision = ModerationDecision.MANUAL_REVIEW
            flags.append(f"override:low_confidence:{confidence:.2f}<{self._settings.llm_confidence_threshold}")
            reason = f"{reason} [Override: low_confidence]".strip()
            llm_data["decision"] = "MANUAL_REVIEW"
            llm_data["flags"] = flags
            llm_data["reason"] = reason

        logger.info(
            "Blog comment AI raw decision",
            decision=decision.value,
            category=str(llm_data.get("category", "ambiguous")),
            confidence=confidence,
            flags=flags,
        )
        ai_result = TextPipelineResult(
            decision=decision,
            category=str(llm_data.get("category", "ambiguous")),
            confidence=confidence,
            reason=reason,
            flags=flags,
            decided_by="llm",
            raw_llm_result=llm_data,
        )
        return self._force_reject_if_violation(ai_result, comment)

    @staticmethod
    def _force_reject_if_violation(ai_result: TextPipelineResult, comment: str) -> TextPipelineResult:
        if ai_result.decision == ModerationDecision.REJECTED:
            return ai_result

        category = ai_result.category.strip().lower()
        flag_set = {flag.strip().lower() for flag in ai_result.flags}
        reason_text = (ai_result.reason or "").strip().lower()
        reason_says_violation = any(token in reason_text for token in _VIOLATION_REASON_TOKENS)

        # Hard profanity is already handled early in _classify_comment, but we check here just in case.
        should_force_reject = category in _FORCE_REJECT_CATEGORIES or any(
            any(token in flag for token in _FORCE_REJECT_FLAGS)
            for flag in flag_set
        ) or has_hard_profanity(comment) or reason_says_violation

        if not should_force_reject:
            return ai_result

        raw = dict(ai_result.raw_llm_result or {})
        raw["decision"] = "REJECTED"
        flags = list(ai_result.flags)
        if "force_reject_violation" not in flags:
            flags.append("force_reject_violation")
        raw["flags"] = flags
        if not raw.get("reason"):
            raw["reason"] = "Detected clear policy violation"
        logger.info(
            "Blog comment force rejected by policy",
            original_decision=ai_result.decision.value,
            category=ai_result.category,
            flags=flags,
        )

        return TextPipelineResult(
            decision=ModerationDecision.REJECTED,
            category=ai_result.category,
            confidence=max(ai_result.confidence, 0.95),
            reason=str(raw.get("reason", "")),
            flags=flags,
            decided_by="post_processor",
            raw_llm_result=raw,
        )

    async def _approve(self, record: BlogCommentRecord, ai_result: TextPipelineResult) -> None:
        await self._repo.update_target_status(
            target_type=record.target_type,
            target_id=record.target_id,
            status=ModerationStatus.APPROVED,
        )
        await self._repo.insert_moderation_log(
            record=record,
            action="AutoApproved",
            moderator_type="AI",
            confidence_score=ai_result.confidence,
            moderation_result=ai_result.raw_llm_result,
        )

    async def _send_to_manual_review(
        self,
        record: BlogCommentRecord,
        ai_result: TextPipelineResult,
    ) -> None:
        await self._repo.update_target_status(
            target_type=record.target_type,
            target_id=record.target_id,
            status=ModerationStatus.MANUAL_REVIEW,
            manual_review_deadline_hours=self._settings.blog_comment_manual_review_timeout_hours,
        )
        await self._repo.insert_moderation_log(
            record=record,
            action="ManualReview",
            moderator_type="AI",
            confidence_score=ai_result.confidence,
            moderation_result=ai_result.raw_llm_result,
        )

    async def _reject(self, record: BlogCommentRecord, ai_result: TextPipelineResult) -> None:
        reason_content = map_ai_category_to_reason_content(
            decision=ai_result.decision,
            category=ai_result.category,
        )
        reason = await self._repo.get_reason_by_content(reason_content or "")
        if reason is None:
            reason = await self._repo.get_default_rejection_reason()
        if reason is None:
            await self._send_to_manual_review(record, ai_result)
            return
        await self._repo.update_target_status(
            target_type=record.target_type,
            target_id=record.target_id,
            status=ModerationStatus.REJECTED,
        )
        await self._repo.insert_moderation_log(
            record=record,
            action="Rejected",
            moderator_type="AI",
            ban_reason_id=reason.ban_reason_id if reason else None,
            confidence_score=ai_result.confidence,
            moderation_result=ai_result.raw_llm_result,
        )
        await self._violation.register_violation_and_lock_if_needed(record.account_id)

    async def _handle_ai_error(self, record: BlogCommentRecord, error_text: str) -> None:
        new_retry_count = record.retry_count + 1
        if self._retry_policy.should_fail(new_retry_count):
            await self._mark_failed(record, new_retry_count, error_text)
            return
        await self._repo.update_target_status(
            target_type=record.target_type,
            target_id=record.target_id,
            status=ModerationStatus.PENDING,
            retry_count=new_retry_count,
        )

    async def _mark_failed(self, record: BlogCommentRecord, retry_count: int, error_text: str) -> None:
        reason = await self._repo.get_reason_by_content(AI_UNAVAILABLE_REASON)
        await self._repo.update_target_status(
            target_type=record.target_type,
            target_id=record.target_id,
            status=ModerationStatus.FAILED,
            retry_count=retry_count,
        )
        await self._repo.insert_moderation_log(
            record=record,
            action="Failed",
            moderator_type="AI",
            ban_reason_id=reason.ban_reason_id if reason else None,
            moderation_result={"error": error_text, "retry_count": retry_count},
        )

    @staticmethod
    def _to_decision(raw: str) -> ModerationDecision:
        value = raw.strip().upper()
        if value == "APPROVED":
            return ModerationDecision.APPROVED
        if value == "REJECTED":
            return ModerationDecision.REJECTED
        return ModerationDecision.MANUAL_REVIEW
