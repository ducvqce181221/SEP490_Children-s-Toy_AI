"""
app/ai/providers/deepseek.py
----------------------------
DeepSeek model provider implementation using httpx.
Triển khai nhà cung cấp mô hình DeepSeek sử dụng httpx để gọi API.
"""

from __future__ import annotations

import json
from typing import Any
import httpx

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.ai.providers.base import AIProvider, AIProviderError
from app.utils.retry import async_retry

# Khởi tạo logger để ghi nhận thông tin log cho module này
logger = get_logger(__name__)


# Lớp triển khai kết nối và gọi API của nhà cung cấp DeepSeek.
# Kế thừa lớp cơ sở AIProvider.
class DeepSeekProvider(AIProvider):

    def __init__(self) -> None:
        # Lấy thông tin cấu hình của hệ thống từ settings
        settings = get_settings()
        # Bắt buộc phải có API key cho DeepSeek trong file config
        if not settings.blog_deepseek_api_key:
            raise ValueError("Missing API key for DeepSeek")
            
        self._api_key = settings.blog_deepseek_api_key
        self._model = settings.blog_deepseek_model
        # Xây dựng danh sách các endpoint dự phòng dựa trên base URL cấu hình
        self._endpoints = self._build_endpoints(settings.blog_deepseek_base_url)
        self._timeout = settings.blog_deepseek_timeout_seconds
        self._retry_attempts = settings.blog_deepseek_retry_attempts

    # Hàm tĩnh hỗ trợ tự động xử lý và định dạng các endpoints API của DeepSeek.
    # Mục đích là tạo danh sách các URL có thể dùng để gửi request chat completion.
    @staticmethod
    def _build_endpoints(base_url: str) -> list[str]:
        # Loại bỏ ký tự gạch chéo '/' ở cuối base url nếu có. Sử dụng api mặc định nếu base_url trống.
        base = (base_url or "https://api.deepseek.com").rstrip("/")
        # Nếu URL đã kết thúc bằng chat/completions thì dùng trực tiếp
        if base.endswith("/chat/completions"):
            return [base]
        # Nếu kết thúc bằng /v1 thì nối thêm chat/completions
        if base.endswith("/v1"):
            return [f"{base}/chat/completions"]
        # Ngược lại, thử cả hai phương án endpoint phổ biến: trực tiếp và qua v1
        return [f"{base}/chat/completions", f"{base}/v1/chat/completions"]

    # Decorator thực hiện cơ chế tự động thử lại (retry) nếu gặp lỗi kết nối hoặc timeout.
    # Số lần thử lại tối đa là 3, thời gian chờ tối thiểu 1s và tối đa 8s giữa các lần thử.
    @async_retry(
        max_attempts=3,
        min_wait=1.0,
        max_wait=8.0,
        exceptions=(httpx.ConnectError, httpx.TimeoutException),
    )
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        # Chuẩn bị dữ liệu gửi đi (payload) cho API DeepSeek
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Nếu có yêu cầu định dạng output cụ thể (ví dụ json_object) thì bổ sung vào payload
        if response_format:
            payload["response_format"] = response_format

        # Cấu hình header chứa token xác thực và định dạng nội dung gửi đi
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error = ""
        # Duyệt qua từng endpoint trong danh sách để gửi request.
        # Nếu endpoint đầu tiên lỗi hoặc không phản hồi đúng, hệ thống sẽ tự chuyển sang endpoint tiếp theo.
        for endpoint in self._endpoints:
            try:
                # Khởi tạo HTTP client bất đồng bộ với timeout xác định
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                # Lỗi kết nối hoặc timeout sẽ ghi log warning và ném ra ngoài để decorator `@async_retry` xử lý thử lại
                logger.warning("DeepSeek timeout/connection error on endpoint", endpoint=endpoint, error=str(exc))
                raise
            except httpx.HTTPError as exc:
                # Các lỗi HTTP chung khác (như lỗi kết nối khác) được ghi nhận và chuyển qua endpoint tiếp theo
                last_error = str(exc)
                logger.error("DeepSeek API request failed", endpoint=endpoint, error=str(exc))
                continue

            # Xử lý trường hợp endpoint trả về mã lỗi 404 (Không tìm thấy)
            if response.status_code == 404:
                last_error = "404 Not Found"
                logger.warning("DeepSeek endpoint returned 404", endpoint=endpoint)
                continue

            # Xử lý các mã lỗi HTTP >= 400 (như 400 Bad Request, 500 Internal Server Error)
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}"
                logger.error("DeepSeek API returned error status", endpoint=endpoint, status=response.status_code)
                continue

            try:
                # Đọc kết quả JSON trả về từ API
                body = response.json()
                # Trích xuất nội dung văn bản được sinh ra từ phản hồi của mô hình
                return body["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                # Nếu cấu trúc JSON trả về không đúng định dạng mong đợi, ghi log error và ném lỗi AIProviderError
                logger.error("DeepSeek response parse envelope failed", endpoint=endpoint, error=str(exc))
                raise AIProviderError("DeepSeek payload parsing failure") from exc

        # Ném lỗi nếu tất cả các endpoint trong danh sách cấu hình đều thử nghiệm thất bại
        raise AIProviderError(f"All DeepSeek endpoints failed. Last error: {last_error}")

