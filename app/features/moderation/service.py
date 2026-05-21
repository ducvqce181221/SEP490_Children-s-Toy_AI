"""
app/features/moderation/service.py
------------------------------------
ModerationOrchestrator — điều phối toàn bộ pipeline kiểm duyệt.
"""

from __future__ import annotations

import asyncio

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

            # 1. Download all images in parallel
            settings = self._settings
            load_tasks = [
                load_image_from_url(
                    url=img_record.image_url,
                    min_size_kb=settings.image_min_size_kb,
                    max_size_mb=settings.image_max_size_mb,
                )
                for img_record in images
            ]
            load_results = await asyncio.gather(*load_tasks, return_exceptions=True)

            # 2. Run local pre-filter on each image
            # State structure: (img_record, raw_bytes, prefilter_result_or_pipeline_result)
            prefilter_states = []
            for img_record, load_res in zip(images, load_results):
                if isinstance(load_res, Exception) or load_res.error or load_res.image is None:
                    err_msg = str(load_res) if isinstance(load_res, Exception) else (load_res.error or "Unknown error")
                    prefilter_states.append((
                        img_record,
                        None,
                        ImagePipelineResult(
                            decision=ModerationDecision.REJECTED,
                            flags=["image_load_failed"],
                            reason=f"Không tải được ảnh: {err_msg}",
                            decided_by="prefilter_load",
                        )
                    ))
                    continue

                prefilter_result = run_image_prefilter(
                    image=load_res.image,
                    raw_bytes=load_res.raw_bytes or b"",
                    existing_phashes=existing_phashes,
                )

                if prefilter_result.decision != ModerationDecision.APPROVED:
                    prefilter_states.append((
                        img_record,
                        None,
                        ImagePipelineResult(
                            decision=prefilter_result.decision,
                            flags=prefilter_result.flags,
                            reason=prefilter_result.reason,
                            decided_by="prefilter",
                            phash=prefilter_result.phash,
                            raw_vision_result={"diagnostics": prefilter_result.diagnostics},
                        )
                    ))
                else:
                    prefilter_states.append((
                        img_record,
                        load_res.raw_bytes or b"",
                        prefilter_result
                    ))

            # 3. Collect images that passed local pre-filters and need Google Vision call
            to_call_vision = [item for item in prefilter_states if not isinstance(item[2], ImagePipelineResult)]

            # 4. Call Google Vision API in batch if there are images
            vision_results = []
            if to_call_vision:
                images_bytes = [item[1] for item in to_call_vision]
                try:
                    vision_results = await get_vision_client().analyze_images_batch(images_bytes)
                except Exception as exc:
                    logger.error("Vision batch API call failed", review_id=review.review_id, error=str(exc))
                    # Treat each as an exception for individual error handling
                    vision_results = [exc] * len(to_call_vision)

            # 5. Process responses and aggregate results
            vision_idx = 0
            for item in prefilter_states:
                img_record = item[0]
                if isinstance(item[2], ImagePipelineResult):
                    image_results.append((img_record.review_product_image_id, item[2]))
                else:
                    prefilter_res = item[2]
                    v_res_or_exc = vision_results[vision_idx]
                    vision_idx += 1

                    if isinstance(v_res_or_exc, Exception):
                        img_pipeline_res = ImagePipelineResult(
                            decision=ModerationDecision.MANUAL_REVIEW,
                            flags=["vision_api_failed"],
                            reason=f"Lỗi Google Vision API: {v_res_or_exc}",
                            decided_by="vision_error",
                            phash=prefilter_res.phash,
                        )
                    else:
                        img_pipeline_res = apply_vision_results(prefilter_res, v_res_or_exc)

                    image_results.append((img_record.review_product_image_id, img_pipeline_res))

        final_decision = self._aggregate_decision(text_result, image_results)

        await self._persist_results(
            review=review, text_result=text_result,
            image_results=image_results, images=images, final_decision=final_decision,
        )

        if final_decision == ModerationDecision.MANUAL_REVIEW:
            manual_reason = "Kiểm tra nội dung"
            if text_result.decision == ModerationDecision.MANUAL_REVIEW:
                manual_reason = text_result.reason
            else:
                for _, img_res in image_results:
                    if img_res.decision == ModerationDecision.MANUAL_REVIEW:
                        manual_reason = img_res.reason
                        break

            await self._send_manual_review_notification(
                review_id=review.review_id,
                reason=manual_reason,
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
