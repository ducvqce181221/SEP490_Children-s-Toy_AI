"""
app/features/moderation/service.py
------------------------------------
ModerationOrchestrator — điều phối toàn bộ pipeline kiểm duyệt.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.features.moderation.image_pipeline.post_processor import apply_vision_results
from app.features.moderation.image_pipeline.prefilter import run_image_prefilter
from app.features.moderation.image_pipeline.vision_client import get_vision_client
from app.features.moderation.repository import ModerationRepository
from app.features.moderation.schemas import (
    ImagePipelineResult, ModerationDecision, ModerationStatus,
    ReviewImageRecord, ReviewRecord, TextPipelineResult,
)
from app.features.moderation.text_pipeline.llm_classifier import run_llm_classifier
from app.features.moderation.text_pipeline.post_processor import PostProcessContext, apply_business_rules
from app.features.moderation.text_pipeline.prefilter import run_prefilter
from app.notification.service import NotificationService
from app.utils.image_utils import load_image_from_url

logger = get_logger(__name__)

_DECISION_TO_STATUS: dict[ModerationDecision, ModerationStatus] = {
    ModerationDecision.APPROVED: ModerationStatus.APPROVED,
    ModerationDecision.REJECTED: ModerationStatus.REJECTED,
    ModerationDecision.MANUAL_REVIEW: ModerationStatus.MANUAL_REVIEW,
}

_SEVERITY: dict[ModerationDecision, int] = {
    ModerationDecision.APPROVED: 0,
    ModerationDecision.MANUAL_REVIEW: 1,
    ModerationDecision.REJECTED: 2,
}


class ModerationOrchestrator:
    def __init__(self) -> None:
        self._repo = ModerationRepository()
        self._notif = NotificationService()
        self._settings = get_settings()

    async def moderate_review(self, review: ReviewRecord) -> None:
        logger.info("Starting moderation", review_id=review.review_id)
        try:
            await self._process(review)
        except Exception as exc:
            logger.error("Unhandled error in moderation pipeline",
                         review_id=review.review_id, error=str(exc), exc_info=True)
            await self._handle_pipeline_failure(review.review_id, str(exc))

    async def _process(self, review: ReviewRecord) -> None:
        images = await self._repo.fetch_images_for_review(review.review_id)
        text_result = await self._run_text_pipeline(review)

        image_results: list[tuple[int, ImagePipelineResult]] = []
        if images:
            existing_phashes = await self._repo.get_existing_phashes(
                min_review_count=self._settings.image_phash_duplicate_min_reviews,
            )
            for img_record in images:
                img_result = await self._run_image_pipeline(img_record, existing_phashes)
                image_results.append((img_record.review_product_image_id, img_result))

        final_decision = self._aggregate_decision(text_result, image_results)

        await self._persist_results(
            review=review, text_result=text_result,
            image_results=image_results, images=images, final_decision=final_decision,
        )

        if final_decision == ModerationDecision.MANUAL_REVIEW:
            await self._send_manual_review_notification(
                review_id=review.review_id,
                reason=text_result.reason if text_result else "Kiểm tra ảnh",
            )

        logger.info("Moderation complete", review_id=review.review_id, final_decision=final_decision)

    async def _run_text_pipeline(self, review: ReviewRecord) -> TextPipelineResult:
        comment = review.comment or ""
        prefilter = run_prefilter(comment)
        if prefilter.rejected:
            return TextPipelineResult(
                decision=ModerationDecision.REJECTED, confidence=1.0,
                category="spam", flags=["prefilter_rejected"],
                reason=prefilter.reason, decided_by="prefilter",
            )

        llm_result = await run_llm_classifier(comment=comment, rating=review.rating)

        recent_rejected = await self._repo.get_recent_rejected_count(
            account_id=review.account_id, days=self._settings.account_rejected_review_days,
        )
        product_created_at = await self._repo.get_product_created_at(review.product_id)
        context = PostProcessContext(
            recent_rejected_count=recent_rejected, product_created_at=product_created_at,
        )
        return apply_business_rules(llm_result, context)

    async def _run_image_pipeline(
        self, img_record: ReviewImageRecord, existing_phashes: list[str],
    ) -> ImagePipelineResult:
        settings = self._settings
        load_result = await load_image_from_url(
            url=img_record.image_url,
            min_size_kb=settings.image_min_size_kb,
            max_size_mb=settings.image_max_size_mb,
        )

        if load_result.error or load_result.image is None:
            return ImagePipelineResult(
                decision=ModerationDecision.REJECTED, flags=["image_load_failed"],
                reason=f"Không tải được ảnh: {load_result.error}", decided_by="prefilter_load",
            )

        prefilter_result = run_image_prefilter(
            image=load_result.image, raw_bytes=load_result.raw_bytes or b"",
            existing_phashes=existing_phashes,
        )

        if prefilter_result.decision != ModerationDecision.APPROVED:
            return ImagePipelineResult(
                decision=prefilter_result.decision, flags=prefilter_result.flags,
                reason=prefilter_result.reason, decided_by="prefilter",
                phash=prefilter_result.phash,
                raw_vision_result={"diagnostics": prefilter_result.diagnostics},
            )

        try:
            vision_result = await get_vision_client().analyze_image(load_result.raw_bytes or b"")
        except Exception as exc:
            logger.error("Vision API failed for image",
                         image_id=img_record.review_product_image_id, error=str(exc))
            return ImagePipelineResult(
                decision=ModerationDecision.MANUAL_REVIEW, flags=["vision_api_failed"],
                reason=f"Lỗi Google Vision API: {exc}", decided_by="vision_error",
                phash=prefilter_result.phash,
            )

        return apply_vision_results(prefilter_result, vision_result)

    def _aggregate_decision(
        self, text_result: TextPipelineResult,
        image_results: list[tuple[int, ImagePipelineResult]],
    ) -> ModerationDecision:
        decisions = [text_result.decision]
        for _, img_result in image_results:
            decisions.append(img_result.decision)
        return max(decisions, key=lambda d: _SEVERITY.get(d, 0))

    async def _persist_results(
        self, review: ReviewRecord, text_result: TextPipelineResult,
        image_results: list[tuple[int, ImagePipelineResult]],
        images: list[ReviewImageRecord], final_decision: ModerationDecision,
    ) -> None:
        final_status = _DECISION_TO_STATUS[final_decision]
        await self._repo.update_review_status(review.review_id, final_status)
        await self._repo.insert_moderation_log(
            review_id=review.review_id, image_id=None, target_type="Text",
            action=_decision_to_action(text_result.decision),
            reason=text_result.reason, moderation_result=text_result.raw_llm_result,
            ai_model_version=self._settings.groq_model,
        )
        for image_id, img_result in image_results:
            img_status = _DECISION_TO_STATUS[img_result.decision]
            await self._repo.update_image_status(image_id, img_status, img_result.phash)
            await self._repo.insert_moderation_log(
                review_id=review.review_id, image_id=image_id, target_type="Image",
                action=_decision_to_action(img_result.decision),
                reason=img_result.reason, moderation_result=img_result.raw_vision_result,
                ai_model_version="google-vision-v1",
            )

    async def _handle_pipeline_failure(self, review_id: int, error_msg: str) -> None:
        failure_count = await self._repo.get_failure_count(review_id)
        if failure_count >= self._settings.max_failure_count_before_alert:
            await self._repo.update_review_status(review_id, ModerationStatus.MANUAL_REVIEW)
            await self._repo.insert_moderation_log(
                review_id=review_id, image_id=None, target_type="Text",
                action="ManualReview",
                reason=f"Pipeline thất bại {failure_count} lần: {error_msg[:200]}",
                moderation_result={"error": error_msg, "failure_count": failure_count},
            )
            await self._send_manual_review_notification(
                review_id=review_id,
                reason=f"Lỗi hệ thống sau {failure_count} lần thử: {error_msg[:150]}",
            )
        else:
            await self._repo.update_review_status(review_id, ModerationStatus.PENDING)
            await self._repo.insert_moderation_log(
                review_id=review_id, image_id=None, target_type="Text",
                action="ManualReview",
                reason=f"Pipeline lỗi lần {failure_count + 1}: {error_msg[:200]}",
                moderation_result={"error": error_msg, "llm_call_failed": True},
            )

    async def _send_manual_review_notification(self, review_id: int, reason: str) -> None:
        accounts = await self._repo.fetch_admin_staff_accounts()
        await self._notif.send_manual_review_alert(
            review_id=review_id, reason=reason, admin_staff_accounts=accounts,
        )


def _decision_to_action(decision: ModerationDecision) -> str:
    return {
        ModerationDecision.APPROVED: "Approved",
        ModerationDecision.REJECTED: "Rejected",
        ModerationDecision.MANUAL_REVIEW: "ManualReview",
    }.get(decision, "ManualReview")
