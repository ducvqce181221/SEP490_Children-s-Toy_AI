"""
app/ai/providers/factory.py
---------------------------
Factory and routing layer for AI providers.
Resolves providers and coordinates API execution with fallback fallback.
Lớp Factory và định tuyến cho các nhà cung cấp AI.
Giải quyết và điều phối việc thực thi API với cơ chế dự phòng (fallback).
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.ai.providers.base import AIProvider, AIProviderError
from app.ai.providers.groq import GroqProvider
from app.ai.providers.deepseek import DeepSeekProvider

# Khởi tạo logger ghi log cho các hoạt động định tuyến và gọi nhà cung cấp AI
logger = get_logger(__name__)

# Registry (Bộ đăng ký/Bộ nhớ đệm) lưu trữ các thực thể (instance) nhà cung cấp AI đã được khởi tạo.
# Tránh việc khởi tạo lại đối tượng ở mỗi lần gọi API.
_providers: dict[str, AIProvider] = {}


def get_provider(name: str) -> AIProvider:
    """
    Get or initialize a model provider by name.
    Supported names: 'groq', 'deepseek'.
    Lấy hoặc khởi tạo đối tượng nhà cung cấp mô hình AI bằng tên định danh.
    Các tên được hỗ trợ: 'groq', 'deepseek'.
    """
    # Chuẩn hóa tên nhà cung cấp (chuyển sang chữ thường và loại bỏ khoảng trắng thừa)
    name = name.lower().strip()
    # Nếu nhà cung cấp chưa có sẵn trong cache _providers, tiến hành khởi tạo mới
    if name not in _providers:
        if name == "groq":
            _providers[name] = GroqProvider()
        elif name == "deepseek":
            _providers[name] = DeepSeekProvider()
        else:
            raise ValueError(f"Unsupported provider: {name}")
    # Trả về đối tượng đã có sẵn trong bộ nhớ đệm
    return _providers[name]


async def execute_chat_completion(
    primary_provider_name: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    response_format: dict[str, Any] | None = None,
    fallback_provider_name: str | None = None,
    **kwargs: Any,
) -> str:
    """
    Execute chat completion with transparent fallback to another provider.

    Args:
        primary_provider_name: Name of the primary provider (e.g. 'groq' or 'deepseek').
        messages: Prompt messages array.
        temperature: Temperature value.
        max_tokens: Max completion tokens.
        response_format: Output format specifications.
        fallback_provider_name: Optional name of the fallback provider to try on failure.

    Returns:
        The generated text completion.

    Raises:
        AIProviderError: If both primary and fallback calls fail.
    """
    # --- BƯỚC 1: Thực hiện gọi nhà cung cấp AI chính (Primary Provider) ---
    try:
        provider = get_provider(primary_provider_name)
        logger.info("Calling primary AI provider", provider=primary_provider_name)
        # Thực hiện gọi phương thức chat completion của nhà cung cấp chính
        return await provider.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            **kwargs,
        )
    except Exception as exc:
        # Nếu nhà cung cấp chính gặp lỗi, ghi log cảnh báo
        logger.warning(
            "Primary AI provider failed",
            provider=primary_provider_name,
            error=str(exc),
        )
        
        # --- BƯỚC 2: Kiểm tra cấu hình dự phòng (Fallback) ---
        # Nếu không cấu hình nhà cung cấp dự phòng, ném trực tiếp lỗi ra ngoài
        if not fallback_provider_name:
            if isinstance(exc, AIProviderError):
                raise
            raise AIProviderError(f"Primary provider {primary_provider_name} failed: {exc}") from exc

        # --- BƯỚC 3: Thực hiện gọi nhà cung cấp AI dự phòng (Fallback Provider) ---
        try:
            logger.info("Executing fallback AI provider", provider=fallback_provider_name)
            fallback_provider = get_provider(fallback_provider_name)
            # Thực hiện gọi phương thức chat completion của nhà cung cấp dự phòng
            return await fallback_provider.chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                **kwargs,
            )
        except Exception as fallback_exc:
            # Ghi log lỗi nghiêm trọng nếu cả nhà cung cấp dự phòng cũng thất bại
            logger.error(
                "Fallback AI provider also failed",
                fallback_provider=fallback_provider_name,
                error=str(fallback_exc),
            )
            # Trả về ngoại lệ phù hợp
            if isinstance(fallback_exc, AIProviderError):
                raise
            raise AIProviderError(
                f"Both primary ({primary_provider_name}) and fallback ({fallback_provider_name}) providers failed."
            ) from fallback_exc

