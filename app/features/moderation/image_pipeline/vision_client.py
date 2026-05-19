"""
app/features/moderation/image_pipeline/vision_client.py
--------------------------------------------------------
Google Cloud Vision API client for SafeSearch + Label Detection.
Makes a single batch request (2 units) to minimise latency and cost.
"""

from __future__ import annotations

from typing import Any

from google.cloud import vision
from google.cloud.vision_v1 import AnnotateImageResponse

from app.core.logging import get_logger
from app.utils.retry import async_retry

logger = get_logger(__name__)

LIKELIHOOD_VALUES: dict[str, int] = {
    "UNKNOWN": 0, "VERY_UNLIKELY": 1, "UNLIKELY": 2,
    "POSSIBLE": 3, "LIKELY": 4, "VERY_LIKELY": 5,
}

ADULT_REJECT_THRESHOLD = "LIKELY"
VIOLENCE_REJECT_THRESHOLD = "LIKELY"
RACY_REJECT_THRESHOLD = "VERY_LIKELY"

TOY_KEYWORDS = {
    "toy", "game", "child", "play", "doll", "lego", "puzzle", "infant",
    "kid", "baby", "figure", "block", "plush", "stuffed", "board game",
    "educational", "toddler", "children", "playful",
}
TOY_LABEL_MIN_SCORE = 0.6
MAX_LABELS = 20


class VisionAnalysisResult:
    def __init__(
        self,
        safe_search: dict[str, str],
        labels: list[dict[str, Any]],
        hard_violation: bool,
        violation_reason: str | None,
        toy_label_found: bool,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        self.safe_search = safe_search
        self.labels = labels
        self.hard_violation = hard_violation
        self.violation_reason = violation_reason
        self.toy_label_found = toy_label_found
        self.raw_response = raw_response or {}


class GoogleVisionClient:
    def __init__(self) -> None:
        self._client = vision.ImageAnnotatorAsyncClient()

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=8.0, exceptions=(Exception,))
    async def analyze_image(self, image_bytes: bytes) -> VisionAnalysisResult:
        image = vision.Image(content=image_bytes)
        features = [
            vision.Feature(type_=vision.Feature.Type.SAFE_SEARCH_DETECTION),
            vision.Feature(type_=vision.Feature.Type.LABEL_DETECTION, max_results=MAX_LABELS),
        ]
        request = vision.AnnotateImageRequest(image=image, features=features)
        response: AnnotateImageResponse = await self._client.annotate_image(request=request)
        return self._parse_response(response)

    def _parse_response(self, response: AnnotateImageResponse) -> VisionAnalysisResult:
        ss = response.safe_search_annotation
        safe_search_dict = {
            "adult": ss.adult.name, "violence": ss.violence.name,
            "racy": ss.racy.name, "spoof": ss.spoof.name, "medical": ss.medical.name,
        }

        hard_violation = False
        violation_reason: str | None = None

        adult_level = LIKELIHOOD_VALUES.get(ss.adult.name, 0)
        violence_level = LIKELIHOOD_VALUES.get(ss.violence.name, 0)
        racy_level = LIKELIHOOD_VALUES.get(ss.racy.name, 0)

        if adult_level >= LIKELIHOOD_VALUES[ADULT_REJECT_THRESHOLD]:
            hard_violation = True
            violation_reason = f"adult content detected: {ss.adult.name}"
        elif violence_level >= LIKELIHOOD_VALUES[VIOLENCE_REJECT_THRESHOLD]:
            hard_violation = True
            violation_reason = f"violence detected: {ss.violence.name}"
        elif racy_level >= LIKELIHOOD_VALUES[RACY_REJECT_THRESHOLD]:
            hard_violation = True
            violation_reason = f"racy content detected: {ss.racy.name}"

        labels = [
            {"description": lbl.description.lower(), "score": lbl.score}
            for lbl in response.label_annotations
        ]

        toy_label_found = False
        if not hard_violation:
            for lbl in labels:
                if lbl["score"] >= TOY_LABEL_MIN_SCORE:
                    if any(kw in lbl["description"] for kw in TOY_KEYWORDS):
                        toy_label_found = True
                        break

        return VisionAnalysisResult(
            safe_search=safe_search_dict,
            labels=labels,
            hard_violation=hard_violation,
            violation_reason=violation_reason,
            toy_label_found=toy_label_found,
            raw_response={"safe_search": safe_search_dict, "labels": labels},
        )


_vision_client: GoogleVisionClient | None = None


def get_vision_client() -> GoogleVisionClient:
    global _vision_client
    if _vision_client is None:
        _vision_client = GoogleVisionClient()
    return _vision_client
