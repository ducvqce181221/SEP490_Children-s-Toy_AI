"""
app/features/moderation/product_review/image_pipeline/post_processor.py
------------------------------------------------------------------------
Bước 3 của image pipeline: Tổng hợp kết quả từ Vision API.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.features.moderation.product_review.image_pipeline.vision_client import VisionAnalysisResult
from app.features.moderation.product_review.image_pipeline.prefilter import PrefilterImageResult
from app.features.moderation.schemas import ImagePipelineResult, ModerationDecision
from app.features.moderation.product_review.text_pipeline.prefilter import find_sensitive_patterns

logger = get_logger(__name__)


def apply_vision_results(
    prefilter_result: PrefilterImageResult,
    vision_result: VisionAnalysisResult,
) -> ImagePipelineResult:
    phash = prefilter_result.phash

    if vision_result.hard_violation:
        return ImagePipelineResult(
            decision=ModerationDecision.REJECTED,
            flags=["vision_hard_violation"],
            reason=f"Vi phạm nghiêm trọng: {vision_result.violation_reason}",
            decided_by="vision_safesearch",
            phash=phash,
            raw_vision_result=vision_result.raw_response,
        )

    if vision_result.detected_text:
        text_violation_reason = find_sensitive_patterns(vision_result.detected_text)
        if text_violation_reason:
            return ImagePipelineResult(
                decision=ModerationDecision.REJECTED,
                flags=["vision_text_violation"],
                reason=f"Ảnh chứa thông tin nhạy cảm: {text_violation_reason}",
                decided_by="vision_ocr",
                phash=phash,
                raw_vision_result=vision_result.raw_response,
            )

    if not vision_result.toy_label_found:
        top_labels = [
            f"{lbl['description']}({lbl['score']:.2f})"
            for lbl in vision_result.labels[:5]
        ]
        return ImagePipelineResult(
            decision=ModerationDecision.MANUAL_REVIEW,
            flags=["no_toy_label"],
            reason=f"Không tìm thấy nhãn đồ chơi phù hợp. Labels: {', '.join(top_labels)}",
            decided_by="vision_labels",
            phash=phash,
            raw_vision_result=vision_result.raw_response,
        )

    top_labels = [
        f"{lbl['description']}({lbl['score']:.2f})"
        for lbl in vision_result.labels[:3]
    ]
    return ImagePipelineResult(
        decision=ModerationDecision.APPROVED,
        flags=[],
        reason=f"Ảnh hợp lệ. Labels: {', '.join(top_labels)}",
        decided_by="vision",
        phash=phash,
        raw_vision_result=vision_result.raw_response,
    )
