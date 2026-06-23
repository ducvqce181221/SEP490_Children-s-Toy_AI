"""
app/application/moderation/product_review.py
--------------------------------------------
ModerationOrchestrator — coordinates the product review moderation pipeline.
"""

from __future__ import annotations

import asyncio

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.application.moderation.image_pipeline import run_image_prefilter, apply_vision_results
from app.integrations.google_vision import get_vision_client
from app.repositories.product_review import ModerationRepository
from app.schemas.moderation import (
    ImagePipelineResult, ModerationDecision, ModerationStatus,
    ReviewImageRecord, ReviewRecord, TextPipelineResult,
)
from app.ai.engines.moderation_engine import run_llm_classifier
from app.application.moderation.business_rules import apply_business_rules, PostProcessContext
from app.ai.engines.content_analyzer import run_prefilter
from app.integrations.notification import NotificationService
from app.utils.image_utils import load_image_from_url
from app.utils.text_utils import analyze_and_sanitize_text

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

    async def get_moderation_stats(self) -> dict[str, int]:
        return await self._repo.get_review_moderation_stats()

    async def moderate_pending_batch(self, batch_size: int = 20) -> int:
        reviews = await self._repo.fetch_pending_reviews(batch_size=batch_size)

        if not reviews:
            logger.debug("No pending reviews found in this cycle")
            return 0

        logger.info("Processing batch", count=len(reviews))

        semaphore = asyncio.Semaphore(self._settings.max_concurrent_reviews)

        async def _process_one(review):
            async with semaphore:
                await self.moderate_review(review)

        await asyncio.gather(*[_process_one(r) for r in reviews], return_exceptions=True)

        logger.info("Batch complete", processed=len(reviews))
        return len(reviews)

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
                            reason=f"Failed to load image: {err_msg}",
                            decided_by="prefilter_load",
                        )
                    ))
                    continue

                prefilter_result = run_image_prefilter(
                    image=load_res.image,
                    raw_bytes=load_res.raw_bytes or b"",
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
                            reason=f"Google Vision API error: {v_res_or_exc}",
                            decided_by="vision_error",
                            phash=prefilter_res.phash,
                        )
                    else:
                        img_pipeline_res = apply_vision_results(prefilter_res, v_res_or_exc)

                        # Run semantic check on OCR text of images if approved and contains OCR text
                        if img_pipeline_res.decision == ModerationDecision.APPROVED and v_res_or_exc.detected_text:
                            meaningful_ocr_len = sum(1 for ch in v_res_or_exc.detected_text if ch.isalnum())
                            if meaningful_ocr_len >= 5:
                                ocr_llm_res = await run_llm_classifier(
                                    comment=v_res_or_exc.detected_text,
                                    rating=review.rating or 5
                                )
                                if ocr_llm_res.decision != ModerationDecision.APPROVED:
                                    img_pipeline_res = ImagePipelineResult(
                                        decision=ocr_llm_res.decision,
                                        flags=ocr_llm_res.flags + ["vision_ocr_llm"],
                                        reason=f"Invalid content detected in image: {ocr_llm_res.reason}",
                                        decided_by="vision_ocr_llm",
                                        phash=prefilter_res.phash,
                                        raw_vision_result={
                                            **v_res_or_exc.raw_response,
                                            "ocr_llm_decision": ocr_llm_res.decision.value,
                                            "ocr_llm_reason": ocr_llm_res.reason
                                        }
                                    )

                    image_results.append((img_record.review_product_image_id, img_pipeline_res))

        final_decision = self._aggregate_decision(text_result, image_results)

        await self._persist_results(
            review=review, text_result=text_result,
            image_results=image_results, images=images, final_decision=final_decision,
        )

        if final_decision == ModerationDecision.MANUAL_REVIEW:
            manual_reason = "Check content"
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
        elif final_decision == ModerationDecision.REJECTED:
            reject_reason = "Content policy violation"
            if text_result.decision == ModerationDecision.REJECTED:
                reject_reason = text_result.reason
            else:
                for _, img_res in image_results:
                    if img_res.decision == ModerationDecision.REJECTED:
                        reject_reason = img_res.reason
                        break

            await self._notif.send_customer_rejection_notification(
                review_id=review.review_id,
                customer_id=review.account_id,
                reason=reject_reason,
            )

        logger.info("Moderation complete", review_id=review.review_id, final_decision=final_decision)

    async def _run_text_pipeline(self, review: ReviewRecord) -> TextPipelineResult:
        comment = (review.comment or "").strip()
        if not comment:
            return TextPipelineResult(
                decision=ModerationDecision.APPROVED, confidence=1.0,
                category="clean", flags=["empty_comment"],
                reason="Rating-only review without comment", decided_by="prefilter",
            )

        normalized, rejected, reason = analyze_and_sanitize_text(comment)
        if rejected:
            return TextPipelineResult(
                decision=ModerationDecision.REJECTED, confidence=1.0,
                category="spam", flags=["prefilter_rejected", "spam_detected"],
                reason=reason, decided_by="prefilter",
            )
        if normalized != comment:
            await self._repo.update_review_comment(review.review_id, normalized)
            comment = normalized
            review.comment = normalized

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
        context = PostProcessContext(
            recent_rejected_count=recent_rejected,
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
        
        text_model = self._settings.groq_model if (text_result.decided_by and text_result.decided_by.startswith("llm")) else None
        text_reason = None if text_result.decision == ModerationDecision.APPROVED else text_result.reason
        await self._repo.insert_moderation_log(
            review_id=review.review_id, image_id=None, target_type="Text",
            action=_decision_to_action(text_result.decision),
            reason=text_reason, moderation_result=text_result.raw_llm_result,
            ai_model_version=text_model,
        )
        for image_id, img_result in image_results:
            img_status = _DECISION_TO_STATUS[img_result.decision]
            await self._repo.update_image_status(image_id, img_status, img_result.phash)
            
            img_model = "google-vision-v1" if (img_result.decided_by and img_result.decided_by.startswith("vision")) else None
            img_reason = None if img_result.decision == ModerationDecision.APPROVED else img_result.reason
            await self._repo.insert_moderation_log(
                review_id=review.review_id, image_id=image_id, target_type="Image",
                action=_decision_to_action(img_result.decision),
                reason=img_reason, moderation_result=img_result.raw_vision_result,
                ai_model_version=img_model,
            )

    async def _handle_pipeline_failure(self, review_id: int, error_msg: str) -> None:
        failure_count = await self._repo.get_failure_count(review_id)
        if failure_count >= self._settings.max_failure_count_before_alert:
            await self._repo.update_review_status(review_id, ModerationStatus.MANUAL_REVIEW)
            await self._repo.insert_moderation_log(
                review_id=review_id, image_id=None, target_type="Text",
                action="ManualReview",
                reason=f"Pipeline failed {failure_count} times: {error_msg[:200]}",
                moderation_result={"error": error_msg, "failure_count": failure_count},
            )
            await self._send_manual_review_notification(
                review_id=review_id,
                reason=f"System error after {failure_count} attempts: {error_msg[:150]}",
            )
        else:
            await self._repo.update_review_status(review_id, ModerationStatus.PENDING)
            await self._repo.insert_moderation_log(
                review_id=review_id, image_id=None, target_type="Text",
                action="ManualReview",
                reason=f"Pipeline error attempt {failure_count + 1}: {error_msg[:200]}",
                moderation_result={"error": error_msg, "llm_call_failed": True},
            )

    async def _send_manual_review_notification(self, review_id: int, reason: str) -> None:
        reviewer_name = await self._repo.get_reviewer_name_by_review_id(review_id)
        accounts = await self._repo.fetch_admin_staff_accounts()
        await self._notif.send_manual_review_alert(
            review_id=review_id,
            reviewer_name=reviewer_name,
            reason=reason,
            admin_staff_accounts=accounts,
        )


def _decision_to_action(decision: ModerationDecision) -> str:
    return {
        ModerationDecision.APPROVED: "Approved",
        ModerationDecision.REJECTED: "Rejected",
        ModerationDecision.MANUAL_REVIEW: "ManualReview",
    }.get(decision, "ManualReview")
