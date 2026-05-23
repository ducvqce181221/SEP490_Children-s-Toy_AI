from __future__ import annotations

import re
import unicodedata

from app.core.config import get_settings
from app.core.logging import get_logger
from app.features.moderation.blog_comment.reason_mapper import (
    AI_UNAVAILABLE_REASON,
    map_ai_category_to_reason_content,
)
from app.features.moderation.blog_comment.repository import BlogCommentModerationRepository
from app.features.moderation.blog_comment.retry_policy import BlogCommentRetryPolicy
from app.features.moderation.blog_comment.schemas import (
    BlogCommentAiResult,
    BlogCommentDecision,
    BlogCommentRecord,
    BlogCommentStatus,
)
from app.features.moderation.blog_comment.violation_service import BlogCommentViolationService
from app.features.moderation.text_pipeline.prefilter import run_prefilter
from app.llm.client import get_blog_deepseek_client

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

_HARD_PROFANITY_PATTERNS: tuple[str, ...] = (
    r"\bcon\s*cac\b",
    r"\bcac\b",
    r"\bdit\b",
    r"\bdm\b",
    r"\bdmm\b",
    r"\bcl\b",
    r"\blo[ln]\b",
    r"\bvai\b",
    r"\bcho\s*de\b",
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

        if ai_result.decision == BlogCommentDecision.APPROVED:
            await self._approve(record, ai_result)
            return
        if ai_result.decision == BlogCommentDecision.MANUAL_REVIEW:
            await self._send_to_manual_review(record, ai_result)
            return
        await self._reject(record, ai_result)

    async def _classify_comment(self, comment: str) -> BlogCommentAiResult:
        prefilter = run_prefilter(comment or "")
        if prefilter.rejected:
            logger.info("Blog comment prefilter rejected", reason=prefilter.reason)
            return BlogCommentAiResult(
                decision=BlogCommentDecision.REJECTED,
                category="spam",
                confidence=1.0,
                reason_text=prefilter.reason,
                flags=["rule_prefilter_reject"],
                raw={
                    "decision": "REJECTED",
                    "confidence": 1.0,
                    "category": "spam",
                    "flags": ["rule_prefilter_reject"],
                    "reason": prefilter.reason,
                },
            )

        llm_data = await get_blog_deepseek_client().classify_text(comment=comment, rating=5)
        decision = self._to_decision(str(llm_data.get("decision", "MANUAL_REVIEW")))
        logger.info(
            "Blog comment AI raw decision",
            decision=decision.value,
            category=str(llm_data.get("category", "ambiguous")),
            confidence=float(llm_data.get("confidence", 0.0)),
            flags=[str(x) for x in llm_data.get("flags", [])],
        )
        ai_result = BlogCommentAiResult(
            decision=decision,
            category=str(llm_data.get("category", "ambiguous")),
            confidence=float(llm_data.get("confidence", 0.0)),
            reason_text=str(llm_data.get("reason", "")),
            flags=[str(x) for x in llm_data.get("flags", [])],
            raw=llm_data,
        )
        return self._force_reject_if_violation(ai_result, comment)

    @staticmethod
    def _force_reject_if_violation(ai_result: BlogCommentAiResult, comment: str) -> BlogCommentAiResult:
        if ai_result.decision == BlogCommentDecision.REJECTED:
            return ai_result

        category = ai_result.category.strip().lower()
        flag_set = {flag.strip().lower() for flag in ai_result.flags}
        reason_text = (ai_result.reason_text or "").strip().lower()
        normalized_comment = BlogCommentModerationService._normalize_text(comment)
        has_hard_profanity = any(re.search(pattern, normalized_comment) for pattern in _HARD_PROFANITY_PATTERNS)
        reason_says_violation = any(token in reason_text for token in _VIOLATION_REASON_TOKENS)
        should_force_reject = category in _FORCE_REJECT_CATEGORIES or any(
            any(token in flag for token in _FORCE_REJECT_FLAGS)
            for flag in flag_set
        ) or has_hard_profanity or reason_says_violation
        if not should_force_reject:
            return ai_result

        raw = dict(ai_result.raw)
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

        return BlogCommentAiResult(
            decision=BlogCommentDecision.REJECTED,
            category=ai_result.category,
            confidence=max(ai_result.confidence, 0.95),
            reason_text=str(raw.get("reason", "")),
            flags=flags,
            raw=raw,
        )

    @staticmethod
    def _normalize_text(text: str | None) -> str:
        base = (text or "").strip().lower()
        if not base:
            return ""
        base = base.replace("đ", "d")
        decomposed = unicodedata.normalize("NFKD", base)
        without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", without_marks)

    async def _approve(self, record: BlogCommentRecord, ai_result: BlogCommentAiResult) -> None:
        await self._repo.update_target_status(
            target_type=record.target_type,
            target_id=record.target_id,
            status=BlogCommentStatus.APPROVED,
        )
        await self._repo.insert_moderation_log(
            record=record,
            action="AutoApproved",
            moderator_type="AI",
            confidence_score=ai_result.confidence,
            moderation_result=ai_result.raw,
        )

    async def _send_to_manual_review(
        self,
        record: BlogCommentRecord,
        ai_result: BlogCommentAiResult,
    ) -> None:
        await self._repo.update_target_status(
            target_type=record.target_type,
            target_id=record.target_id,
            status=BlogCommentStatus.MANUAL_REVIEW,
            manual_review_deadline_hours=self._settings.blog_comment_manual_review_timeout_hours,
        )
        await self._repo.insert_moderation_log(
            record=record,
            action="ManualReview",
            moderator_type="AI",
            confidence_score=ai_result.confidence,
            moderation_result=ai_result.raw,
        )

    async def _reject(self, record: BlogCommentRecord, ai_result: BlogCommentAiResult) -> None:
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
            status=BlogCommentStatus.REJECTED,
        )
        await self._repo.insert_moderation_log(
            record=record,
            action="Rejected",
            moderator_type="AI",
            ban_reason_id=reason.ban_reason_id if reason else None,
            confidence_score=ai_result.confidence,
            moderation_result=ai_result.raw,
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
            status=BlogCommentStatus.PENDING,
            retry_count=new_retry_count,
        )

    async def _mark_failed(self, record: BlogCommentRecord, retry_count: int, error_text: str) -> None:
        reason = await self._repo.get_reason_by_content(AI_UNAVAILABLE_REASON)
        await self._repo.update_target_status(
            target_type=record.target_type,
            target_id=record.target_id,
            status=BlogCommentStatus.FAILED,
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
    def _to_decision(raw: str) -> BlogCommentDecision:
        value = raw.strip().upper()
        if value == "APPROVED":
            return BlogCommentDecision.APPROVED
        if value == "REJECTED":
            return BlogCommentDecision.REJECTED
        return BlogCommentDecision.MANUAL_REVIEW
