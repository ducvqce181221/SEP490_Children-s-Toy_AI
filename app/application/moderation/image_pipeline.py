"""
app/application/moderation/image_pipeline.py
--------------------------------------------
Local image pre-processing (OpenCV, Pillow, pHash) and post-processing of Vision API results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import cv2
import numpy as np
from PIL import Image

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.schemas.moderation import ModerationDecision, ImagePipelineResult
from app.utils.text_utils import has_hard_profanity, clean_and_normalize_text
from app.ai.engines.content_analyzer import find_sensitive_patterns
from app.integrations.google_vision import VisionAnalysisResult

logger = get_logger(__name__)

_RESIZE_DIM = 512


@dataclass
class PrefilterImageResult:
    decision: ModerationDecision
    flags: list[str] = field(default_factory=list)
    reason: str = ""
    diagnostics: dict = field(default_factory=dict)


def run_image_prefilter(
    image: Image.Image,
    raw_bytes: bytes,
) -> PrefilterImageResult:
    settings = get_settings()

    try:
        img_cv = _pil_to_cv2_gray(image)
    except Exception as exc:
        logger.warning("OpenCV conversion failed", error=str(exc))
        return PrefilterImageResult(
            decision=ModerationDecision.MANUAL_REVIEW,
            flags=["opencv_error"],
            reason=f"Cannot analyze image quality: {exc}",
        )

    mean_brightness = float(np.mean(img_cv))
    std_dev = float(np.std(img_cv))
    diagnostics = {"mean_brightness": round(mean_brightness, 2), "std_dev": round(std_dev, 2)}

    if mean_brightness < 20:
        return PrefilterImageResult(
            decision=ModerationDecision.REJECTED, flags=["black_image"],
            reason=f"Dark image (mean brightness={mean_brightness:.1f} < 20)",
            diagnostics=diagnostics,
        )

    if std_dev < 10:
        return PrefilterImageResult(
            decision=ModerationDecision.REJECTED, flags=["uniform_image"],
            reason=f"Uniform image, no content (std_dev={std_dev:.1f} < 10)",
            diagnostics=diagnostics,
        )

    img_resized = cv2.resize(img_cv, (_RESIZE_DIM, _RESIZE_DIM))
    laplacian_var = float(cv2.Laplacian(img_resized, cv2.CV_64F).var())
    lv_normalized = laplacian_var / (mean_brightness + 1.0)
    diagnostics["laplacian_var"] = round(laplacian_var, 4)
    diagnostics["lv_normalized"] = round(lv_normalized, 4)

    reject_thresh = settings.image_blur_lv_reject_threshold

    if lv_normalized < reject_thresh:
        return PrefilterImageResult(
            decision=ModerationDecision.REJECTED, flags=["blurry_image"],
            reason=f"Blurry image (LV_normalized={lv_normalized:.3f} < {reject_thresh})",
            diagnostics=diagnostics,
        )

    return PrefilterImageResult(
        decision=ModerationDecision.APPROVED, flags=[],
        reason="Passed local pre-filter", diagnostics=diagnostics,
    )


def _pil_to_cv2_gray(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)


def apply_vision_results(
    prefilter_result: PrefilterImageResult,
    vision_result: VisionAnalysisResult,
) -> ImagePipelineResult:

    if vision_result.hard_violation:
        return ImagePipelineResult(
            decision=ModerationDecision.REJECTED,
            flags=["vision_hard_violation"],
            reason=f"Severe violation: {vision_result.violation_reason}",
            decided_by="vision_safesearch",
            raw_vision_result=vision_result.raw_response,
        )

    if vision_result.detected_text:
        normalized_ocr = clean_and_normalize_text(vision_result.detected_text)
        if has_hard_profanity(vision_result.detected_text) or has_hard_profanity(normalized_ocr):
            return ImagePipelineResult(
                decision=ModerationDecision.REJECTED,
                flags=["vision_profanity_violation"],
                reason="Image contains extreme vulgar profanity (auto-blocked from OCR)",
                decided_by="vision_ocr_profanity",
                raw_vision_result=vision_result.raw_response,
            )

        text_violation_reason = find_sensitive_patterns(vision_result.detected_text)
        if not text_violation_reason:
            text_violation_reason = find_sensitive_patterns(normalized_ocr)

        if text_violation_reason:
            return ImagePipelineResult(
                decision=ModerationDecision.REJECTED,
                flags=["vision_text_violation"],
                reason=f"Image contains sensitive information: {text_violation_reason}",
                decided_by="vision_ocr",
                raw_vision_result=vision_result.raw_response,
            )

    if not vision_result.toy_label_found:
        top_labels = [
            f"{lbl['description']}({lbl['score']:.2f})"
            for lbl in vision_result.labels[:5]
        ]
        return ImagePipelineResult(
            decision=ModerationDecision.REJECTED,
            flags=["no_toy_label"],
            reason=f"No matching toy label found. Labels: {', '.join(top_labels)}",
            decided_by="vision_labels",
            raw_vision_result=vision_result.raw_response,
        )

    top_labels = [
        f"{lbl['description']}({lbl['score']:.2f})"
        for lbl in vision_result.labels[:3]
    ]
    return ImagePipelineResult(
        decision=ModerationDecision.APPROVED,
        flags=[],
        reason=f"Valid image. Labels: {', '.join(top_labels)}",
        decided_by="vision",
        raw_vision_result=vision_result.raw_response,
    )
