"""
app/features/moderation/image_pipeline/prefilter.py
----------------------------------------------------
Bước 1 của image pipeline: Pre-filter hoàn toàn local (Pillow + OpenCV).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from app.core.config import get_settings
from app.core.logging import get_logger
from app.features.moderation.schemas import ModerationDecision, ImagePipelineResult
from app.utils.phash import compute_phash

logger = get_logger(__name__)

_RESIZE_DIM = 512


@dataclass
class PrefilterImageResult:
    decision: ModerationDecision
    flags: list[str] = field(default_factory=list)
    reason: str = ""
    phash: str | None = None
    diagnostics: dict = field(default_factory=dict)


def run_image_prefilter(
    image: Image.Image,
    raw_bytes: bytes,
    existing_phashes: list[str],
) -> PrefilterImageResult:
    settings = get_settings()

    phash = _compute_phash_safe(image)

    if existing_phashes and phash:
        from app.utils.phash import is_duplicate
        if is_duplicate(phash, existing_phashes, threshold=settings.image_phash_hamming_distance):
            return PrefilterImageResult(
                decision=ModerationDecision.REJECTED,
                flags=["phash_duplicate"],
                reason="Ảnh trùng lặp với review khác (pHash duplicate)",
                phash=phash,
            )

    try:
        img_cv = _pil_to_cv2_gray(image)
    except Exception as exc:
        logger.warning("OpenCV conversion failed", error=str(exc))
        return PrefilterImageResult(
            decision=ModerationDecision.MANUAL_REVIEW,
            flags=["opencv_error"],
            reason=f"Không thể phân tích chất lượng ảnh: {exc}",
            phash=phash,
        )

    mean_brightness = float(np.mean(img_cv))
    std_dev = float(np.std(img_cv))
    diagnostics = {"mean_brightness": round(mean_brightness, 2), "std_dev": round(std_dev, 2)}

    if mean_brightness < 20:
        return PrefilterImageResult(
            decision=ModerationDecision.REJECTED, flags=["black_image"],
            reason=f"Ảnh tối (mean brightness={mean_brightness:.1f} < 20)",
            phash=phash, diagnostics=diagnostics,
        )

    if std_dev < 10:
        return PrefilterImageResult(
            decision=ModerationDecision.REJECTED, flags=["uniform_image"],
            reason=f"Ảnh đồng màu, không có nội dung (std_dev={std_dev:.1f} < 10)",
            phash=phash, diagnostics=diagnostics,
        )

    img_resized = cv2.resize(img_cv, (_RESIZE_DIM, _RESIZE_DIM))
    laplacian_var = float(cv2.Laplacian(img_resized, cv2.CV_64F).var())
    lv_normalized = laplacian_var / (mean_brightness + 1.0)
    diagnostics["laplacian_var"] = round(laplacian_var, 4)
    diagnostics["lv_normalized"] = round(lv_normalized, 4)

    reject_thresh = settings.image_blur_lv_reject_threshold
    manual_thresh = settings.image_blur_lv_manual_review_threshold

    if lv_normalized < reject_thresh:
        return PrefilterImageResult(
            decision=ModerationDecision.REJECTED, flags=["blurry_image"],
            reason=f"Ảnh mờ/nhòe (LV_normalized={lv_normalized:.3f} < {reject_thresh})",
            phash=phash, diagnostics=diagnostics,
        )

    if lv_normalized < manual_thresh:
        return PrefilterImageResult(
            decision=ModerationDecision.MANUAL_REVIEW, flags=["possibly_blurry"],
            reason=f"Ảnh nghi mờ (LV_normalized={lv_normalized:.3f}, ngưỡng manual={manual_thresh})",
            phash=phash, diagnostics=diagnostics,
        )

    return PrefilterImageResult(
        decision=ModerationDecision.APPROVED, flags=[],
        reason="Passed local pre-filter", phash=phash, diagnostics=diagnostics,
    )


def _pil_to_cv2_gray(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)


def _compute_phash_safe(image: Image.Image) -> str | None:
    try:
        return compute_phash(image)
    except Exception as exc:
        logger.warning("pHash computation failed", error=str(exc))
        return None
