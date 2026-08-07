"""
app/application/blog_generation/service.py
-------------------------------------------
Application Service điều phối quy trình sinh nội dung bài viết Blog bằng AI.

Tập trung vào:
1. Kiểm tra tính hợp lệ của dữ liệu đầu vào (Validation & Emoji check).
2. Phân loại ý định chủ đề (Intent Gate) để ngăn chặn sinh các bài viết lạc đề/ngoài phạm vi cửa hàng đồ chơi.
3. Kiểm tra an toàn trước khi gọi AI (Safety Pre-check) để phát hiện từ cấm, nhãn hiệu đối thủ, nội dung nhạy cảm.
4. Quản lý bộ nhớ tạm (In-memory Cache với mã băm SHA256 & thời gian sống TTL) để giảm thiểu chi phí API LLM.
5. Gọi AI Generation Engine (DeepSeek / Groq fallback) để sinh nội dung HTML chất lượng cao.
6. Kiểm duyệt an toàn văn bản đầu ra (Output Validation) trước khi gửi kết quả về cho client.
"""

from __future__ import annotations

import time
import hashlib
from typing import Any

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.ai.engines.blog_engine import execute_blog_generation, generate_smart_suggestions
from app.ai.engines.content_analyzer import (
    safety_check,
    classify_intent,
    _check_hard_block_emoji,
    _build_source_content_warning,
    output_validation,
    DEFAULT_BLOCK_SUGGESTIONS,
)

# Khởi tạo logger để theo dõi nhật ký hoạt động của service
logger = get_logger(__name__)

# Cấu hình cho Cache lưu kết quả tạo bài viết:
# _GENERATE_CACHE_TTL_SECONDS: Thời gian tồn tại của 1 kết quả cache (300 giây = 5 phút)
# _GENERATE_CACHE_MAX_ITEMS: Số lượng bài viết tối đa được lưu trữ đồng thời trong bộ nhớ RAM
_GENERATE_CACHE_TTL_SECONDS = 300.0
_GENERATE_CACHE_MAX_ITEMS = 128
_GENERATE_RESULT_CACHE: dict[str, tuple[float, tuple[str, str]]] = {}


class BlogContentGenerationError(RuntimeError):
    """Ngoại lệ tùy chỉnh đại diện cho các lỗi phát sinh trong quá trình AI tạo nội dung bài viết Blog."""
    pass


def _make_generate_cache_key(
    action: str,
    title: str,
    description: str | None,
    prompt_structure: str,
    tone: str,
    category_id: int,
    source_content: str | None,
) -> str:
    """
    Tạo mã băm SHA256 độc nhất dựa trên tập hợp tất cả các tham số đầu vào của request.
    Key này được sử dụng để kiểm tra xem request tương tự đã từng được tạo gần đây hay chưa.
    
    Args:
        action: Hành động yêu cầu ("Generate", "Improve", "Rewrite")
        title: Tiêu đề đầu vào
        description: Mô tả chi tiết (nếu có)
        prompt_structure: Cấu trúc dàn ý hoặc gợi ý nội dung
        tone: Giọng văn ("Friendly", "Expert", v.v.)
        category_id: ID danh mục đồ chơi/bài viết
        source_content: Văn bản nguồn cung cấp (nếu có)
        
    Returns:
        Chuỗi mã băm Hex SHA256 đại diện cho request.
    """
    raw = "|".join([
        action or "",
        title or "",
        description or "",
        prompt_structure or "",
        tone or "",
        str(category_id),
        source_content or "",
    ])
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _cache_get(key: str) -> tuple[str, str] | None:
    """
    Tra cứu và lấy kết quả bài viết từ Cache bộ nhớ tạm.
    
    Logic kiểm tra:
    - Nếu key không tồn tại -> Trả về None (Cache Miss).
    - Nếu key tồn tại nhưng thời gian lưu giữ đã vượt quá TTL (300s) -> Tự động xóa khỏi Cache và trả về None.
    - Nếu key hợp lệ và còn trong thời hạn -> Trả về tuple (tiêu đề, nội dung HTML).
    """
    now = time.monotonic()
    cached = _GENERATE_RESULT_CACHE.get(key)
    if not cached:
        return None
    ts, value = cached
    # Kiểm tra thời hạn hết hạn Cache (TTL)
    if now - ts > _GENERATE_CACHE_TTL_SECONDS:
        _GENERATE_RESULT_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: tuple[str, str]) -> None:
    """
    Lưu trữ kết quả bài viết mới sinh vào Cache bộ nhớ tạm.
    
    Nếu số lượng phần tử trong Cache đạt hoặc vượt quá giới hạn tối đa (_GENERATE_CACHE_MAX_ITEMS = 128),
    hệ thống sẽ tự động tìm và loại bỏ phần tử cũ nhất (Lowest Timestamp) để giải phóng bộ nhớ.
    """
    now = time.monotonic()
    if len(_GENERATE_RESULT_CACHE) >= _GENERATE_CACHE_MAX_ITEMS:
        # Tìm key của phần tử có mốc thời gian lưu (ts) nhỏ nhất để xóa
        oldest_key = min(_GENERATE_RESULT_CACHE.items(), key=lambda item: item[1][0])[0]
        _GENERATE_RESULT_CACHE.pop(oldest_key, None)
    _GENERATE_RESULT_CACHE[key] = (now, value)


async def generate_blog_content(
    *,
    action: str,
    title: str,
    description: str | None,
    prompt_structure: str,
    tone: str,
    category_id: int,
    source_content: str | None,
) -> tuple[str, str] | dict[str, str | list[str]]:
    """
    Hàm chính điều phối toàn bộ quy trình sinh nội dung bài viết Blog bằng AI.
    
    Quy trình xử lý gồm 8 bước nghiêm ngặt:
    --------------------------------------
    Bước 1: Validate tính hợp lệ của tham số cơ bản (Tiêu đề, dàn ý, categoryId).
    Bước 2: Kiểm tra các Emoji độc hại hoặc bị cấm trong tiêu đề & dàn ý.
    Bước 3: Phân loại ý định chủ đề (Intent Gate) để chặn các chủ đề không liên quan đến đồ chơi/trẻ em/phụ huynh.
    Bước 4: Kiểm tra an toàn từ khóa nhạy cảm (Safety Pre-check) & tự động tạo danh sách gợi ý thay thế (Smart Suggestions).
    Bước 5: Kiểm tra cảnh báo từ văn bản nguồn (Source Content Warning).
    Bước 6: Tra cứu Cache bộ nhớ tạm (tránh gọi LLM trùng lặp trong 5 phút).
    Bước 7: Gọi AI Engine (DeepSeek/Groq) thực thi sinh bài viết theo chiến lược dàn ý.
    Bước 8: Kiểm duyệt an toàn văn bản HTML đầu ra (Output Validation).
    
    Returns:
        - Nối tiếp thành công: tuple(generated_title, generated_html_content)
        - Nếu bị chặn: dict đại diện cho response bị block (status, violation_type, violated_keyword, reason, suggestions).
    """
    logger.info(
        "AI blog generation requested",
        action=action,
        title_len=len(title or ""),
        prompt_len=len(prompt_structure or ""),
        has_source=bool(source_content),
        category_id=category_id,
    )

    # =========================================================================
    # Bước 1: Kiểm tra tính hợp lệ của dữ liệu yêu cầu đầu vào
    # =========================================================================
    # Tiêu đề và khung prompt_structure không được để trống; category_id phải > 0
    if not (title or "").strip() or not (prompt_structure or "").strip() or category_id <= 0:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": "validation_error",
            "reason": "invalid_request",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    # =========================================================================
    # Bước 2: Kiểm tra các Emoji bị cấm / không thích hợp
    # =========================================================================
    blocked_emoji = _check_hard_block_emoji(title, prompt_structure)
    if blocked_emoji:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": blocked_emoji,
            "reason": "inappropriate_emoji",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    # =========================================================================
    # Bước 3: Phân loại ý định chủ đề (Intent Gate Classification)
    # =========================================================================
    # Mục đích: Đảm bảo bài viết được sinh ra chỉ tập trung vào lĩnh vực Đồ chơi trẻ em, Mẹo nuôi dạy con,
    # Sự phát triển của trẻ, An toàn đồ chơi. Chặn các chủ đề chính trị, tài chính, đồ dùng người lớn, v.v.
    intent = classify_intent(
        title=title,
        description=description,
        prompt_structure=prompt_structure,
        category_id=category_id,
    )
    if str(intent.get("decision")) == "block":
        logger.info(
            "Blog generation blocked by intent gate",
            reason=intent.get("reason"),
            confidence=intent.get("confidence"),
            source=intent.get("source"),
        )
        return {
            "status": "blocked",
            "violation_type": "out_of_scope",
            "violated_keyword": "off_topic",
            "reason": "off_topic",
            "suggestions": [str(intent.get("suggestion", DEFAULT_BLOCK_SUGGESTIONS[0]))] + DEFAULT_BLOCK_SUGGESTIONS[:3],
        }
    if str(intent.get("decision")) == "review":
        logger.info(
            "Intent gate uncertain, allow generation",
            reason=intent.get("reason"),
            confidence=intent.get("confidence"),
            source=intent.get("source"),
        )

    # =========================================================================
    # Bước 4: Kiểm tra an toàn tiền xử lý (Safety Pre-check)
    # =========================================================================
    # Quét tiêu đề & khung gợi ý để phát hiện các từ cấm, nhãn hiệu đối thủ cạnh tranh, từ ngữ vi phạm.
    violation = safety_check(title=title, prompt_structure=prompt_structure)
    if violation:
        # Nếu phát hiện vi phạm, gọi AI hoặc danh sách fallback để tạo 4 gợi ý thay thế thông minh (Smart Suggestions)
        smart_suggestions = await generate_smart_suggestions(
            title=title,
            content=(description or prompt_structure or "").strip(),
            violated_keyword=str(violation.get("violated_keyword", "")),
            violation_reason=str(violation.get("reason", "")),
        )
        violation["suggestions"] = smart_suggestions[:4] if smart_suggestions else DEFAULT_BLOCK_SUGGESTIONS[:4]
        logger.info(
            "Blog generation blocked by pre-check",
            violation_type=violation.get("violation_type"),
            violated_keyword=violation.get("violated_keyword"),
        )
        return violation

    # =========================================================================
    # Bước 5: Kiểm tra cảnh báo từ dữ liệu nguồn cung cấp (Source Content Warning)
    # =========================================================================
    source_warning = _build_source_content_warning(source_content)
    if source_warning:
        logger.warning("Source content moderation warning", detail=source_warning)

    # =========================================================================
    # Bước 6: Tra cứu Cache bộ nhớ tạm
    # =========================================================================
    cache_key = _make_generate_cache_key(
        action=action, title=title, description=description,
        prompt_structure=prompt_structure, tone=tone, category_id=category_id,
        source_content=source_content,
    )
    cached_result = _cache_get(cache_key)
    if cached_result is not None:
        logger.info("AI blog generation cache hit", title_len=len(title or ""))
        return cached_result

    # =========================================================================
    # Bước 7: Thực thi gọi AI Engine sinh nội dung bài viết
    # =========================================================================
    try:
        generated_title, generated_content = await execute_blog_generation(
            action=action, title=title, description=description,
            prompt_structure=prompt_structure, tone=tone, category_id=category_id,
            source_content=source_content,
        )
    except Exception as exc:
        raise BlogContentGenerationError(f"AI content generation failed: {exc}") from exc

    # =========================================================================
    # Bước 8: Kiểm duyệt an toàn cho bài viết đầu ra (Output Validation)
    # =========================================================================
    # Đảm bảo bài viết HTML do AI tạo ra không chứa mã độc, nội dung vi phạm hoặc lỗi cấu trúc
    validation_status, validation_payload = output_validation(generated_content)
    if validation_status == "reject":
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": str(validation_payload),
            "reason": "unsafe_output",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    # Đưa kết quả thành công vào Cache và trả về cho caller
    result = (generated_title, validation_payload)
    _cache_put(cache_key, result)
    return result


