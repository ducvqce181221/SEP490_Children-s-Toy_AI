# ------------------------------------------------------------------------------
# app/configs/config.py
# ------------------------------------------------------------------------------
# Quản lý tập trung các thông số cấu hình hệ thống bằng pydantic-settings.
# Tất cả các giá trị biến môi trường được tự động nạp từ tệp `.env` hoặc biến môi trường hệ thống.
# ------------------------------------------------------------------------------

from __future__ import annotations

import os
import tempfile
import base64
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Class định nghĩa danh mục các thông số cấu hình chính cho toàn bộ ứng dụng AI
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 1. Cấu hình chung Ứng dụng (App Environment & Log Level) ──────────────
    app_env: Literal["development", "production"] = "development" # Môi trường chạy ứng dụng
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO" # Mức độ ghi nhật ký
    internal_api_key: str = Field(
        default="change-me",
        validation_alias=AliasChoices(
            "INTERNAL_API_KEY",
            "AI_INTERNAL_API_KEY",
            "BLOG_COMMENT_INTERNAL_API_KEY",
        ),
        description="Mã khóa API nội bộ xác thực giữa C# Backend và Python AI Sidecar",
    )

    # ── 2. Cấu hình Kết nối CSDL SQL Server ──────────────────────────────────
    mssql_connection_string: str = Field(..., description="Chuỗi kết nối pyodbc/aioodbc đầy đủ tới SQL Server")

    # ── 3. Cấu hình Dịch vụ AI Groq LLM (Primary cho Review / Fallback cho Blog) ─
    groq_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GROQ_API_KEY"),
        description="Khóa API Groq cho quy trình kiểm duyệt đánh giá sản phẩm",
    )
    groq_model: str = Field(
        default="openai/gpt-oss-20b",
        validation_alias=AliasChoices("GROQ_MODEL"),
    )
    groq_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GROQ_BASE_URL"),
        description="URL gốc tùy chỉnh chuẩn OpenAI cho Groq Client",
    )
    groq_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    groq_max_tokens: int = Field(default=1000, gt=0)

    # ── 4. Cấu hình Dịch vụ AI DeepSeek LLM (Chuyên dụng cho Blog AI) ─────────
    blog_deepseek_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("BLOG_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
        description="Khóa API DeepSeek chuyên dụng cho sinh & kiểm duyệt nội dung Blog",
    )
    blog_deepseek_model: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices("BLOG_DEEPSEEK_MODEL", "DEEPSEEK_MODEL"),
    )
    blog_deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("BLOG_DEEPSEEK_BASE_URL", "DEEPSEEK_BASE_URL"),
    )
    blog_deepseek_temperature: float = Field(
        default=0.85,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices("BLOG_DEEPSEEK_TEMPERATURE"),
    )
    blog_deepseek_max_tokens: int = Field(
        default=2200,
        gt=0,
        validation_alias=AliasChoices("BLOG_DEEPSEEK_MAX_TOKENS"),
    )
    blog_deepseek_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        validation_alias=AliasChoices("BLOG_DEEPSEEK_TIMEOUT_SECONDS"),
    )
    blog_deepseek_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        validation_alias=AliasChoices("BLOG_DEEPSEEK_RETRY_ATTEMPTS"),
    )

    # ── 5. Cấu hình Chứng thực Google Cloud Vision API ───────────────────────
    google_application_credentials: str | None = None # Đường dẫn tệp JSON credential
    google_application_credentials_json: str | None = None # Dữ liệu chuỗi base64 JSON credential

    # ── 6. Cấu hình Tiến trình Chạy nền (Background Workers & Jobs) ───────────
    trigger_mode: Literal["POLL", "OUTBOX", "API"] = "API"
    poll_interval_seconds: int = Field(default=30, gt=0) # Chu kỳ quét dữ liệu (giây)
    max_concurrent_reviews: int = Field(default=5, gt=0) # Số lượng kiểm duyệt đồng thời tối đa
    max_retry_attempts: int = Field(default=3, ge=1) # Số lần thử lại tối đa khi gặp lỗi
    max_failure_count_before_alert: int = Field(default=5, ge=1) # Số lần lỗi tối đa trước khi gửi cảnh báo
    blog_comment_retry_interval_minutes: int = Field(default=5, gt=0) # Khoảng thời gian giãn cách thử lại bình luận lỗi (phút)
    blog_comment_manual_review_timeout_hours: int = Field(default=24, gt=0) # Hạn chót duyệt tay tự động từ chối (24 giờ)
    blog_comment_lock_days: int = Field(default=7, gt=0) # Số ngày phạt khóa quyền gửi bình luận (7 ngày)
    blog_comment_violation_threshold: int = Field(default=20, gt=0) # Ngưỡng số lần vi phạm để kích hoạt phạt khóa

    # ── 7. Ngưỡng Cấu hình Xử lý Hình ảnh ─────────────────────────────────────
    image_min_size_kb: int = Field(default=10, gt=0) # Dung lượng tệp ảnh tối thiểu (10 KB)
    image_max_size_mb: int = Field(default=5, gt=0) # Dung lượng tệp ảnh tối đa (5 MB)
    image_blur_lv_reject_threshold: float = Field(default=1.0, gt=0) # Ngưỡng độ mờ hình ảnh

    # ── 8. Quy tắc Nghiệp vụ (Business Rules & Thresholds) ────────────────────
    account_rejected_review_days: int = Field(default=30, gt=0)
    account_rejected_review_max: int = Field(default=2, ge=1)
    llm_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0) # Ngưỡng độ tin cậy AI tối thiểu (0.70)

    # Hàm giải mã chứng thực Google Cloud Credentials thành tệp tạm thời nếu dạng Base64
    def resolve_google_credentials(self) -> str | None:
        if self.google_application_credentials_json:
            json_bytes = base64.b64decode(self.google_application_credentials_json)
            tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb")
            tmp.write(json_bytes)
            tmp.flush()
            tmp.close()
            return tmp.name
        return self.google_application_credentials

    # Hàm gán biến môi trường GOOGLE_APPLICATION_CREDENTIALS cho SDK nhận diện
    def setup_google_credentials_env(self) -> None:
        path = self.resolve_google_credentials()
        if path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path


# Hàm lấy instance Settings bộ nhớ đệm (LRU Cache Singleton)
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

