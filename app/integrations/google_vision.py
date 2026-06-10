"""
app/integrations/google_vision.py
----------------------------------
Google Cloud Vision API client for SafeSearch + Label Detection.
Makes a single batch request (2 units) to minimise latency and cost.
"""

from __future__ import annotations

import asyncio
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
    # Costume & Character Pretend Play categories
    "mask", "masque", "costume", "mascot", "fictional character", "superhero",
    "cosplay", "pretend play", "roleplay", "character", "action figure", "merchandise",
    # Product & Packaging terms to prevent false positives on toy boxes
    "product", "packaged product", "box", "packaging", "gift", "carton", "cardboard box",
    # Physical toy material & vehicle terms
    "plastic", "wooden", "wood", "fabric", "textile", "miniature", "model", "scale model",
    "vehicle", "car", "train", "airplane", "truck", "motorcycle", "figurine", "collectible",
    "novelty", "hobby", "recreation"
}

REAL_WEAPON_LABELS = {
    "firearm", "handgun", "rifle", "shotgun", "assault weapon", "tactical firearm",
    "revolver", "military weapon", "machine gun", "carbine", "sniper rifle",
    "ammunition", "weapon sales", "bullet", "ammunition belt"
}

AMBIGUOUS_WEAPON_LABELS = {
    "weapon", "knife", "gun", "pistol"
}

TOY_WEAPON_INDICATORS = {
    "toy", "water gun", "nerf", "blaster", "plaything", "plastic", "cartoon",
    "water pistol", "child play weapon", "cosplay", "foam", "play weapon", "model"
}

OTHER_SUSPICIOUS_LABELS = {
    "fight", "fighting", "wrestling", "altercation", "aggression", "assault",
    "physical conflict", "bullying", "smoking", "alcohol", "beer", "wine",
    "gamble", "gambling", "casino",
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
        detected_text: str | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        self.safe_search = safe_search
        self.labels = labels
        self.hard_violation = hard_violation
        self.violation_reason = violation_reason
        self.toy_label_found = toy_label_found
        self.detected_text = detected_text
        self.raw_response = raw_response or {}


class GoogleVisionClient:
    def __init__(self) -> None:
        # Use the SYNC client — run in a thread to avoid blocking the event loop.
        self._client = vision.ImageAnnotatorClient()

    def _call_vision_api(self, image_bytes: bytes) -> AnnotateImageResponse:
        """Blocking call to Vision API — executed in a thread pool."""
        image = vision.Image(content=image_bytes)
        features = [
            vision.Feature(type_=vision.Feature.Type.SAFE_SEARCH_DETECTION),
            vision.Feature(type_=vision.Feature.Type.LABEL_DETECTION, max_results=MAX_LABELS),
            vision.Feature(type_=vision.Feature.Type.TEXT_DETECTION),
        ]
        request = vision.AnnotateImageRequest(image=image, features=features)
        response: AnnotateImageResponse = self._client.annotate_image(request=request)
        return response

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=8.0, exceptions=(Exception,))
    async def analyze_image(self, image_bytes: bytes) -> VisionAnalysisResult:
        response: AnnotateImageResponse = await asyncio.to_thread(
            self._call_vision_api, image_bytes
        )
        return self._parse_response(response)

    def _call_vision_api_batch(self, images_bytes: list[bytes]) -> list[AnnotateImageResponse]:
        """Blocking call to Vision API for batch annotation — executed in a thread pool."""
        requests = []
        for img_bytes in images_bytes:
            image = vision.Image(content=img_bytes)
            features = [
                vision.Feature(type_=vision.Feature.Type.SAFE_SEARCH_DETECTION),
                vision.Feature(type_=vision.Feature.Type.LABEL_DETECTION, max_results=MAX_LABELS),
                vision.Feature(type_=vision.Feature.Type.TEXT_DETECTION),
            ]
            requests.append(vision.AnnotateImageRequest(image=image, features=features))
        
        response = self._client.batch_annotate_images(requests=requests)
        return list(response.responses)

    @async_retry(max_attempts=3, min_wait=1.0, max_wait=8.0, exceptions=(Exception,))
    async def analyze_images_batch(self, images_bytes: list[bytes]) -> list[VisionAnalysisResult]:
        if not images_bytes:
            return []
        responses = await asyncio.to_thread(self._call_vision_api_batch, images_bytes)
        return [self._parse_response(resp) for resp in responses]

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

        # Check for suspicious/violating content based on labels
        has_toy_indicator = False
        if not hard_violation:
            for lbl in labels:
                if lbl["score"] >= 0.50:
                    desc = lbl["description"].lower()
                    if any(indicator in desc for indicator in TOY_WEAPON_INDICATORS):
                        has_toy_indicator = True
                        break

            for lbl in labels:
                if lbl["score"] >= 0.60:
                    desc = lbl["description"].lower()

                    # 1. Other Suspicious Labels (non-weapon, e.g. alcohol, gambling) are always rejected
                    if any(other in desc for other in OTHER_SUSPICIOUS_LABELS):
                        hard_violation = True
                        violation_reason = f"suspicious content label detected: {desc}"
                        break

                    # 2. Weapon checks (both real firearms and ambiguous weapons) are skipped entirely if a toy indicator is present
                    if not has_toy_indicator:
                        if any(real in desc for real in REAL_WEAPON_LABELS):
                            hard_violation = True
                            violation_reason = f"real weapon detected: {desc}"
                            break

                        if any(ambiguous in desc for ambiguous in AMBIGUOUS_WEAPON_LABELS):
                            hard_violation = True
                            violation_reason = f"unverified weapon/firearm detected: {desc}"
                            break

        toy_label_found = False
        if not hard_violation:
            if has_toy_indicator:
                toy_label_found = True
            else:
                for lbl in labels:
                    if lbl["score"] >= TOY_LABEL_MIN_SCORE:
                        if any(kw in lbl["description"].lower() for kw in TOY_KEYWORDS):
                            toy_label_found = True
                            break

        detected_text = None
        if response.text_annotations:
            detected_text = response.text_annotations[0].description

        return VisionAnalysisResult(
            safe_search=safe_search_dict,
            labels=labels,
            hard_violation=hard_violation,
            violation_reason=violation_reason,
            toy_label_found=toy_label_found,
            detected_text=detected_text,
            raw_response={
                "safe_search": safe_search_dict,
                "labels": labels,
                "detected_text": detected_text,
            },
        )


_vision_client: GoogleVisionClient | None = None


def get_vision_client() -> GoogleVisionClient:
    global _vision_client
    if _vision_client is None:
        _vision_client = GoogleVisionClient()
    return _vision_client
