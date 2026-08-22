"""
app/ai/providers/groq.py
-------------------------
Groq model provider implementation.
Triển khai nhà cung cấp mô hình Groq.
"""

from __future__ import annotations

from typing import Any
from groq import AsyncGroq, APIConnectionError, APIStatusError, APITimeoutError

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.ai.providers.base import AIProvider, AIProviderError
from app.utils.retry import async_retry

# Khởi tạo logger ghi nhận thông tin logs cho GroqProvider
logger = get_logger(__name__)


# Lớp triển khai kết nối và gọi API của nhà cung cấp Groq.
# Kế thừa lớp cơ sở AIProvider.
class GroqProvider(AIProvider):

    def __init__(self) -> None:
        # Lấy thông tin cấu hình từ settings hệ thống
        settings = get_settings()
        # Bắt buộc phải có API key cho Groq
        if not settings.groq_api_key:
            raise ValueError("Missing API key for Groq")
        
        # Cấu hình tham số khởi tạo cho client của Groq SDK
        client_kwargs: dict[str, Any] = {"api_key": settings.groq_api_key}
        # Nếu cấu hình có chứa base URL riêng cho Groq, thêm vào tham số khởi tạo client
        if settings.groq_base_url:
            client_kwargs["base_url"] = settings.groq_base_url
            
        # Khởi tạo Groq client dạng bất đồng bộ (AsyncGroq)
        self._client = AsyncGroq(**client_kwargs)
        # Lưu trữ mô hình sẽ sử dụng
        self._model = settings.groq_model

    # Decorator thực hiện cơ chế tự động thử lại (retry) nếu gặp lỗi kết nối hoặc timeout từ phía API Groq.
    # Số lần thử tối đa là 3, thời gian chờ tối thiểu 1s và tối đa 8s giữa các lần thử.
    @async_retry(
        max_attempts=3,
        min_wait=1.0,
        max_wait=8.0,
        exceptions=(APIConnectionError, APITimeoutError),
    )
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            # Thiết lập các tham số cơ bản cho yêu cầu gọi API chat completions
            call_kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            # Bổ sung response_format nếu được yêu cầu (ví dụ: ép đầu ra về dạng JSON)
            if response_format:
                call_kwargs["response_format"] = response_format

            # Gọi bất đồng bộ API chat completion của Groq
            response = await self._client.chat.completions.create(**call_kwargs)
            # Trả về nội dung phản hồi từ mô hình
            return response.choices[0].message.content or ""
        except APIStatusError as exc:
            # Bắt các lỗi phản hồi HTTP không thành công từ phía Groq API (ví dụ: 400, 401, 429, 500)
            logger.error(
                "Groq API returned error status",
                status=exc.status_code,
                message=exc.message,
            )
            # Ném ra lỗi AIProviderError bọc ngoài ngoại lệ gốc để chuẩn hóa lỗi ở tầng xử lý trên
            raise AIProviderError(f"Groq API error {exc.status_code}: {exc.message}") from exc
        except Exception as exc:
            # Bắt tất cả các lỗi không mong muốn khác trong quá trình gọi API
            logger.error("Groq chat completion call failed", error=str(exc))
            raise AIProviderError(f"Groq failure: {exc}") from exc

