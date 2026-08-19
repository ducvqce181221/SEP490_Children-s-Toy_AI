# ------------------------------------------------------------------------------
# app/ai/engines/moderation_engine.py
# ------------------------------------------------------------------------------
# AI Moderation Engine: Đóng gói Prompt, gọi dịch vụ LLM Provider (DeepSeek / Groq),
# trích xuất & parse phản hồi JSON, và chuyển đổi kết quả thành TextPipelineResult.
# ------------------------------------------------------------------------------

from __future__ import annotations

import json
import re
from typing import Any

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.schemas.moderation import ModerationDecision, TextPipelineResult
from app.ai.prompts.templates import SYSTEM_PROMPT, build_user_prompt
from app.ai.providers.factory import execute_chat_completion
from app.utils.text_utils import clean_and_normalize_text

logger = get_logger(__name__)

# Kết quả dự phòng mặc định khi LLM gặp sự cố parse JSON hoặc lỗi kết nối
_FALLBACK_RESULT: dict[str, Any] = {
    "decision": "MANUAL_REVIEW", # Chuyển duyệt tay an toàn
    "confidence": 0.0,
    "category": "ambiguous",
    "flags": ["llm_parse_error"],
    "reason": "Failed to parse LLM result, fallback to manual review",
}


# Hàm trích xuất và parse chuỗi phản hồi JSON từ AI LLM (DeepSeek / Groq)
def _parse_llm_json(raw: str) -> dict[str, Any]:
    """
    Trích xuất và parse chuỗi phản hồi JSON từ AI LLM:
    - Chuẩn hóa trường 'decision' (APPROVED, REJECTED, MANUAL_REVIEW).
    - Kiểm tra và ép kiểu điểm tin cậy 'confidence' trong khoảng từ 0.0 đến 1.0.
    - Xử lý danh sách các cờ vi phạm 'flags' và lý do 'reason'.
    - Nếu chuỗi JSON bị lỗi không parse được -> Tự động chuyển về _FALLBACK_RESULT (MANUAL_REVIEW).
    """
    try:
        raw_clean = raw.strip()

        # 1. Loại bỏ các thẻ suy luận <think>...</think> nếu có từ các mô hình reasoning
        raw_clean = re.sub(r"<think>.*?</think>", "", raw_clean, flags=re.DOTALL).strip()

        # 2. Tìm kiếm khối markdown json ```json ... ``` hoặc ``` ... ```
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_clean, flags=re.DOTALL)
        if code_block:
            raw_clean = code_block.group(1).strip()
        else:
            # 3. Tìm kiếm khối JSON bao bọc bởi { ... }
            json_block = re.search(r"(\{.*\})", raw_clean, flags=re.DOTALL)
            if json_block:
                raw_clean = json_block.group(1).strip()

        # 4. Sửa lỗi trailing comma phổ biến trong JSON do LLM sinh ra (ví dụ: {"a": 1, })
        raw_clean = re.sub(r",\s*([\]}])", r"\1", raw_clean)

        # Parse dữ liệu JSON
        data = json.loads(raw_clean)
        
        # 1. Trích xuất và chuẩn hóa trường decision (APPROVED, REJECTED, MANUAL_REVIEW)
        decision_val = data.get("decision", "MANUAL_REVIEW")
        decision_str = str(decision_val).upper()
        if decision_str not in {"APPROVED", "REJECTED", "MANUAL_REVIEW"}:
            decision_str = "MANUAL_REVIEW"
            
        # 2. Trích xuất và ép kiểu điểm số tin cậy confidence (0.0 đến 1.0)
        confidence_val = data.get("confidence")
        try:
            confidence = float(confidence_val) if confidence_val is not None else (1.0 if decision_str == "APPROVED" else 0.5)
        except (ValueError, TypeError):
            confidence = 0.5
            
        if not 0.0 <= confidence <= 1.0:
            confidence = 0.5
            
        # 3. Trích xuất danh mục vi phạm (category)
        category = str(data.get("category", "ambiguous")).lower()
        
        # 4. Trích xuất danh sách các cờ phát hiện vi phạm (flags)
        flags = data.get("flags")
        if not isinstance(flags, list):
            flags = []
        else:
            flags = [str(f) for f in flags]
            
        # 5. Trích xuất lý do giải thích từ AI (reason)
        reason = str(data.get("reason", ""))
        
        return {
            "decision": decision_str,
            "confidence": confidence,
            "category": category,
            "flags": flags,
            "reason": reason,
        }
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        # Ghi log cảnh báo khi không thể parse chuỗi JSON từ AI
        logger.warning(
            "LLM JSON parsing failed",
            raw_response=raw[:200],
            error=str(exc),
        )
        return {**_FALLBACK_RESULT, "flags": ["llm_parse_error"]}


# Hàm phân loại nội dung đánh giá sản phẩm (Product Review) bằng AI LLM
async def run_llm_classifier(
    comment: str,
    rating: int,
) -> TextPipelineResult:
    """
    Phân loại nội dung đánh giá sản phẩm (Product Review) bằng AI.
    Sử dụng Groq làm provider chính và DeepSeek làm provider dự phòng (fallback).
    """
    settings = get_settings()
    # Bước 1: Chuẩn hóa văn bản tiếng Việt không dấu và làm sạch teencode
    normalized = clean_and_normalize_text(comment)
    # Bước 2: Xây dựng User Prompt gửi cho AI
    user_message = build_user_prompt(
        content=comment,
        content_type="review",
        rating=rating,
        normalized_content=normalized,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        # Bước 3: Thực thi gọi LLM Provider (Groq làm Provider chính, DeepSeek làm dự phòng)
        raw_completion = await execute_chat_completion(
            primary_provider_name="groq",
            messages=messages,
            temperature=settings.groq_temperature,
            max_tokens=settings.groq_max_tokens,
            response_format={"type": "json_object"},
            fallback_provider_name="deepseek",
        )
        # Bước 4: Parse dữ liệu phản hồi JSON
        result = _parse_llm_json(raw_completion)
    except Exception as exc:
        # Xử lý khi tất cả các provider AI đều gặp sự cố kết nối
        logger.error("LLM review classification failed after all retries/fallbacks", error=str(exc))
        return TextPipelineResult(
            decision=ModerationDecision.MANUAL_REVIEW,
            confidence=0.0,
            category="ambiguous",
            flags=["llm_call_failed"],
            reason="LLM call error, fallback to manual review",
            decided_by="llm_error",
        )

    # Chuyển đổi kết quả sang Enum ModerationDecision
    decision_str = result.get("decision", "MANUAL_REVIEW").upper()
    try:
        decision = ModerationDecision(decision_str)
    except ValueError:
        decision = ModerationDecision.MANUAL_REVIEW

    # Bước 5: Đóng gói và trả về đối tượng TextPipelineResult
    return TextPipelineResult(
        decision=decision,
        confidence=float(result.get("confidence", 0.0)),
        category=str(result.get("category", "ambiguous")),
        flags=list(result.get("flags", [])),
        reason=str(result.get("reason", "")),
        decided_by="llm",
        raw_llm_result=result,
    )


# Hàm phân loại nội dung bình luận / phản hồi Blog bằng AI LLM
async def run_blog_comment_classifier(
    comment: str,
) -> dict[str, Any]:
    """
    Phân loại nội dung bình luận / phản hồi Blog bằng AI:
    
    Quy trình hoạt động:
    --------------------
    1. Làm sạch văn bản bình luận bằng `clean_and_normalize_text`.
    2. Dựng prompt gửi AI (`build_user_prompt` với content_type="comment").
    3. Đóng gói message với System Prompt quy định rõ các quy tắc an toàn.
    4. Gọi AI Provider:
       - Đơn vị ưu tiên số 1: DeepSeek AI (nhạy bén trong xử lý tiếng Việt ngữ cảnh & văn phong trẻ em).
       - Đơn vị dự phòng số 2: Groq AI (tự động kích hoạt nếu DeepSeek gặp sự cố/timeout).
    5. Parse kết quả trả về bằng `_parse_llm_json`.
    
    Returns:
        Dictionary chứa các thông tin: decision, confidence, category, flags, reason.
    """
    settings = get_settings()
    # Bước 1: Chuẩn hóa ký tự và dọn dẹp văn bản
    normalized = clean_and_normalize_text(comment)
    # Bước 2: Dựng nội dung user prompt cho AI
    user_message = build_user_prompt(
        content=comment,
        content_type="comment",
        rating=None,
        normalized_content=normalized,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        # Bước 3: Thực thi gọi AI Provider (DeepSeek chính -> Groq dự phòng)
        raw_completion = await execute_chat_completion(
            primary_provider_name="deepseek",
            messages=messages,
            temperature=settings.blog_deepseek_temperature,
            max_tokens=settings.blog_deepseek_max_tokens,
            response_format={"type": "json_object"},
            fallback_provider_name="groq",
        )
        # Bước 4: Parse kết quả JSON trả về
        return _parse_llm_json(raw_completion)
    except Exception as exc:
        # Xử lý khi tất cả các provider AI đều gặp lỗi
        logger.error("LLM blog comment classification failed after all retries/fallbacks", error=str(exc))
        return {**_FALLBACK_RESULT, "flags": ["llm_call_failed"]}


# Hàm phân loại nội dung chữ trích xuất từ hình ảnh (Image OCR Text) bằng AI LLM
async def run_image_ocr_classifier(
    detected_text: str,
) -> TextPipelineResult:
    """
    Phân loại nội dung văn bản OCR trích xuất từ hình ảnh đánh giá sản phẩm.
    Quy tắc đặc thù cho OCR ảnh:
    - Các watermark thương hiệu, tên shop, logo (ví dụ: "TAM SHOPPE", "Shopee", "Tiki", "Lazada", "TikTok"),
      thông tin bao bì sản phẩm, tên mô hình đồ chơi và cảnh báo an toàn được coi là hợp lệ (APPROVED).
    - Chỉ từ chối (REJECTED) nếu phát hiện ngôn từ tục tĩu nặng, thù địch, nội dung đồi trụy hoặc lừa đảo.
    - Nếu LLM gặp sự cố parse hoặc lỗi kết nối, an toàn cho qua (APPROVED) vì ảnh đã qua các bước lọc regex cục bộ.
    """
    settings = get_settings()
    normalized = clean_and_normalize_text(detected_text)
    user_message = build_user_prompt(
        content=detected_text,
        content_type="image_ocr",
        rating=None,
        normalized_content=normalized,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        raw_completion = await execute_chat_completion(
            primary_provider_name="groq",
            messages=messages,
            temperature=settings.groq_temperature,
            max_tokens=settings.groq_max_tokens,
            response_format={"type": "json_object"},
            fallback_provider_name="deepseek",
        )
        result = _parse_llm_json(raw_completion)
    except Exception as exc:
        logger.warning("LLM image OCR classification failed, falling back to safe approval", error=str(exc))
        return TextPipelineResult(
            decision=ModerationDecision.APPROVED,
            confidence=0.85,
            category="clean",
            flags=["ocr_llm_skipped_on_error"],
            reason="Image OCR passed local prefilter checks",
            decided_by="vision_ocr_fallback",
        )

    # Nếu LLM gặp lỗi parse JSON (ví dụ kết quả không hợp lệ), không chặn ảnh của khách
    if "llm_parse_error" in result.get("flags", []):
        logger.warning("Image OCR LLM parse error, falling back to approved", detected_text=detected_text[:100])
        return TextPipelineResult(
            decision=ModerationDecision.APPROVED,
            confidence=0.85,
            category="clean",
            flags=["ocr_llm_parse_fallback"],
            reason="Image OCR text is benign (passed local checks)",
            decided_by="vision_ocr_fallback",
        )

    decision_str = result.get("decision", "APPROVED").upper()
    try:
        decision = ModerationDecision(decision_str)
    except ValueError:
        decision = ModerationDecision.APPROVED

    return TextPipelineResult(
        decision=decision,
        confidence=float(result.get("confidence", 0.9)),
        category=str(result.get("category", "clean")),
        flags=list(result.get("flags", [])),
        reason=str(result.get("reason", "Valid image OCR text")),
        decided_by="vision_ocr_llm",
        raw_llm_result=result,
    )




