"""
app/core/config.py
------------------
Centralized settings management via pydantic-settings.
All values are read from environment variables (or .env file).
"""

from __future__ import annotations

import os
import tempfile
import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_env: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    internal_api_key: str = Field(default="change-me", description="Key for /moderation/trigger")

    # ── Database ─────────────────────────────────────────────────────────
    mssql_connection_string: str = Field(..., description="Full pyodbc connection string for SQL Server")

    # ── Groq LLM ─────────────────────────────────────────────────────────
    groq_api_key: str = Field(..., description="Groq API key")
    groq_model: str = "llama-3.1-8b-instant"
    groq_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    groq_max_tokens: int = Field(default=200, gt=0)

    # ── Google Cloud Vision ───────────────────────────────────────────────
    google_application_credentials: str | None = None
    google_application_credentials_json: str | None = None

    # ── Worker ───────────────────────────────────────────────────────────
    trigger_mode: Literal["POLL", "OUTBOX"] = "POLL"
    poll_interval_seconds: int = Field(default=30, gt=0)
    max_concurrent_reviews: int = Field(default=5, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    max_failure_count_before_alert: int = Field(default=5, ge=1)

    # ── Image thresholds ─────────────────────────────────────────────────
    image_min_size_kb: int = Field(default=10, gt=0)
    image_max_size_mb: int = Field(default=10, gt=0)
    image_blur_lv_reject_threshold: float = Field(default=1.0, gt=0)
    image_blur_lv_manual_review_threshold: float = Field(default=2.5, gt=0)
    image_phash_hamming_distance: int = Field(default=10, ge=0)
    image_phash_duplicate_min_reviews: int = Field(default=5, ge=1)

    # ── Business rules ───────────────────────────────────────────────────
    account_rejected_review_days: int = Field(default=30, gt=0)
    account_rejected_review_max: int = Field(default=2, ge=1)
    new_product_days: int = Field(default=7, gt=0)
    llm_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)

    @field_validator("image_blur_lv_manual_review_threshold")
    @classmethod
    def manual_threshold_must_exceed_reject(cls, v: float, info) -> float:  # noqa: ANN001
        reject = info.data.get("image_blur_lv_reject_threshold", 1.0)
        if v <= reject:
            raise ValueError(
                "image_blur_lv_manual_review_threshold must be > image_blur_lv_reject_threshold"
            )
        return v

    def resolve_google_credentials(self) -> str | None:
        if self.google_application_credentials_json:
            json_bytes = base64.b64decode(self.google_application_credentials_json)
            tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb")
            tmp.write(json_bytes)
            tmp.flush()
            tmp.close()
            return tmp.name
        return self.google_application_credentials

    def setup_google_credentials_env(self) -> None:
        path = self.resolve_google_credentials()
        if path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
