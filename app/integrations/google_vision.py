# ------------------------------------------------------------------------------
# app/integrations/google_vision.py
# ------------------------------------------------------------------------------
# Client tích hợp Google Cloud Vision API thực hiện kiểm duyệt hình ảnh:
# 1. SafeSearch Detection: Nhận diện nội dung người lớn (adult), bạo lực (violence), nhạy cảm (racy).
# 2. Label Detection: Phân tích các nhãn vật thể xuất hiện trong ảnh (Đồ chơi, vũ khí, đồ uống cấm, v.v.).
# 3. Text Detection (OCR): Trích xuất văn bản có trong hình ảnh đánh giá.
# ------------------------------------------------------------------------------

from __future__ import annotations

import asyncio
from typing import Any

from google.cloud import vision
from google.cloud.vision_v1 import AnnotateImageResponse

from app.core.logging import get_logger
from app.utils.retry import async_retry

logger = get_logger(__name__)

# Ánh xạ mức độ khả thi của Google SafeSearch sang giá trị số (0 đến 5)
LIKELIHOOD_VALUES: dict[str, int] = {
    "UNKNOWN": 0, "VERY_UNLIKELY": 1, "UNLIKELY": 2,
    "POSSIBLE": 3, "LIKELY": 4, "VERY_LIKELY": 5,
}

# Ngưỡng từ chối hình ảnh cho từng danh mục nhạy cảm
ADULT_REJECT_THRESHOLD = "LIKELY"  # Từ chối nếu nội dung người lớn >= LIKELIHOOD 4 (LIKELY)
VIOLENCE_REJECT_THRESHOLD = "LIKELY"  # Từ chối nếu bạo lực >= LIKELIHOOD 4 (LIKELY)
RACY_REJECT_THRESHOLD = "VERY_LIKELY"  # Từ chối nếu gợi dục >= LIKELIHOOD 5 (VERY_LIKELY)

# Tập hợp từ khóa nhãn nhận diện đồ chơi & phụ kiện trẻ em (Dùng để xác nhận ảnh hợp lệ)
TOY_KEYWORDS = {
    "toy", "game", "child", "play", "doll", "lego", "puzzle", "infant",
    "kid", "baby", "figure", "block", "plush", "stuffed", "board game",
    "educational", "toddler", "children", "playful",
    # Từ khóa đóng vai, hóa trang & nhân vật hoạt hình
    "mask", "masque", "costume", "mascot", "fictional character", "superhero",
    "cosplay", "pretend play", "roleplay", "character", "action figure", "merchandise",
    # Từ khóa bao bì, vỏ hộp sản phẩm đồ chơi
    "product", "packaged product", "box", "packaging", "gift", "carton", "cardboard box",
    # Từ khóa chất liệu đồ chơi & phương tiện mô hình
    "plastic", "wooden", "wood", "fabric", "textile", "miniature", "model", "scale model",
    "vehicle", "car", "train", "airplane", "truck", "motorcycle", "figurine", "collectible",
    "novelty", "hobby", "recreation"
}

# Nhãn vũ khí thật (Luôn bị chặn nếu phát hiện)
REAL_WEAPON_LABELS = {
    "firearm", "handgun", "rifle", "shotgun", "assault weapon", "tactical firearm",
    "revolver", "military weapon", "machine gun", "carbine", "sniper rifle",
    "ammunition", "weapon sales", "bullet", "ammunition belt"
}

# Nhãn vũ khí có tính chất mơ hồ (Cần kiểm tra thêm yếu tố súng đồ chơi / nhựa)
AMBIGUOUS_WEAPON_LABELS = {
    "weapon", "knife", "gun", "pistol"
}

# Chỉ báo từ khóa súng đồ chơi / đồ chơi nhựa (Giúp bỏ qua vi phạm nhầm cho súng nước, súng xốp Nerf)
TOY_WEAPON_INDICATORS = {
    "toy", "water gun", "nerf", "blaster", "plaything", "plastic", "cartoon",
    "water pistol", "child play weapon", "cosplay", "foam", "play weapon", "model"
}

# Nhãn các vật thể nghi vấn độc hại khác (Rượu, bia, thuốc lá, cờ bạc, bạo lực)
OTHER_SUSPICIOUS_LABELS = {
    "fight", "fighting", "wrestling", "altercation", "aggression", "assault",
    "physical conflict", "bullying", "smoking", "alcohol", "beer", "wine",
    "gamble", "gambling", "casino",
}

# Điểm số tin cậy tối thiểu cho nhãn đồ chơi (0.60 = 60%)
TOY_LABEL_MIN_SCORE = 0.6
# Số lượng nhãn tối đa lấy từ Google Vision API trong 1 yêu cầu
MAX_LABELS = 20


# Class chứa kết quả phân tích hình ảnh từ Google Vision API
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
        self.safe_search = safe_search  # Kết quả SafeSearch (adult, violence, racy, v.v.)
        self.labels = labels  # Danh sách các nhãn vật thể phát hiện được
        self.hard_violation = hard_violation  # Cờ đánh dấu có vi phạm quy tắc nghiêm trọng hay không
        self.violation_reason = violation_reason  # Lý do vi phạm cụ thể
        self.toy_label_found = toy_label_found  # Cờ đánh dấu có tìm thấy nhãn đồ chơi hợp lệ hay không
        self.detected_text = detected_text  # Văn bản OCR trích xuất từ hình ảnh
        self.raw_response = raw_response or {}  # Phản hồi dữ liệu gốc từ API


# Client gọi dịch vụ Google Cloud Vision API
class GoogleVisionClient:
    def __init__(self) -> None:
        # Khởi tạo client đồng bộ — sẽ được thực thi trong ThreadPool để không làm nghẽn Event Loop
        self._client = vision.ImageAnnotatorClient()

    # Hàm gọi Vision API đồng bộ cho 1 hình ảnh đơn lẻ
    def _call_vision_api(self, image_bytes: bytes) -> AnnotateImageResponse:
        image = vision.Image(content=image_bytes)
        features = [
            vision.Feature(type_=vision.Feature.Type.SAFE_SEARCH_DETECTION),
            vision.Feature(type_=vision.Feature.Type.LABEL_DETECTION, max_results=MAX_LABELS),
            vision.Feature(type_=vision.Feature.Type.TEXT_DETECTION),
        ]
        request = vision.AnnotateImageRequest(image=image, features=features)
        response: AnnotateImageResponse = self._client.annotate_image(request=request)
        return response

    # Hàm bất đồng bộ phân tích 1 hình ảnh (Tự động retry 3 lần nếu gặp lỗi)
    @async_retry(max_attempts=3, min_wait=1.0, max_wait=8.0, exceptions=(Exception,))
    async def analyze_image(self, image_bytes: bytes) -> VisionAnalysisResult:
        # Chạy hàm gọi API đồng bộ trong Thread Pool để giữ Event Loop bất đồng bộ không bị chặn
        response: AnnotateImageResponse = await asyncio.to_thread(
            self._call_vision_api, image_bytes
        )
        return self._parse_response(response)

    # Hàm gọi Vision API đồng bộ cho một lô (Batch) nhiều hình ảnh cùng lúc
    def _call_vision_api_batch(self, images_bytes: list[bytes]) -> list[AnnotateImageResponse]:
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

    # Hàm bất đồng bộ phân tích một lô hình ảnh cùng lúc
    @async_retry(max_attempts=3, min_wait=1.0, max_wait=8.0, exceptions=(Exception,))
    async def analyze_images_batch(self, images_bytes: list[bytes]) -> list[VisionAnalysisResult]:
        if not images_bytes:
            return []
        responses = await asyncio.to_thread(self._call_vision_api_batch, images_bytes)
        return [self._parse_response(resp) for resp in responses]

    # Hàm đọc và phân tích kết quả AnnotateImageResponse từ Google Vision API
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

        # 1. Kiểm tra các vi phạm SafeSearch (Nội dung người lớn, bạo lực, gợi dục)
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

        # 2. Kiểm tra các nhãn vi phạm hoặc nhãn súng đồ chơi / đồ chơi nhựa
        has_toy_indicator = False
        if not hard_violation:
            # Kiểm tra xem ảnh có chứa chỉ báo súng đồ chơi/súng nước hay không
            for lbl in labels:
                if lbl["score"] >= 0.50:
                    desc = lbl["description"].lower()
                    if any(indicator in desc for indicator in TOY_WEAPON_INDICATORS):
                        has_toy_indicator = True
                        break

            for lbl in labels:
                if lbl["score"] >= 0.60:
                    desc = lbl["description"].lower()

                    # Kiểm tra các nhãn độc hại nghi vấn khác (Rượu, bia, cờ bạc) -> Bắt lỗi ngay
                    if any(other in desc for other in OTHER_SUSPICIOUS_LABELS):
                        hard_violation = True
                        violation_reason = f"suspicious content label detected: {desc}"
                        break

                    # Nếu không có chỉ báo súng đồ chơi -> Kiểm tra vi phạm nhãn vũ khí/súng thật
                    if not has_toy_indicator:
                        if any(real in desc for real in REAL_WEAPON_LABELS):
                            hard_violation = True
                            violation_reason = f"real weapon detected: {desc}"
                            break

                        if any(ambiguous in desc for ambiguous in AMBIGUOUS_WEAPON_LABELS):
                            hard_violation = True
                            violation_reason = f"unverified weapon/firearm detected: {desc}"
                            break

        # 3. Kiểm tra xem ảnh có chứa nhãn đồ chơi hợp lệ hay không
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

        # 4. Trích xuất văn bản OCR trong hình ảnh (nếu có)
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


# Lưu trữ instance Singleton của GoogleVisionClient
_vision_client: GoogleVisionClient | None = None


# Hàm lấy hoặc khởi tạo instance Singleton của GoogleVisionClient
def get_vision_client() -> GoogleVisionClient:
    global _vision_client
    if _vision_client is None:
        _vision_client = GoogleVisionClient()
    return _vision_client

