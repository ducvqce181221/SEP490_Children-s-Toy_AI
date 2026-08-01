"""
app/configs/config.py
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

from pydantic import AliasChoices, Field
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
    internal_api_key: str = Field(
        default="change-me",
        validation_alias=AliasChoices(
            "INTERNAL_API_KEY",
            "AI_INTERNAL_API_KEY",
            "BLOG_COMMENT_INTERNAL_API_KEY",
        ),
        description="Key for /moderation/trigger",
    )

    # ── Database ─────────────────────────────────────────────────────────
    mssql_connection_string: str = Field(..., description="Full pyodbc connection string for SQL Server")

    # ── Groq LLM ─────────────────────────────────────────────────────────
    groq_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GROQ_API_KEY"),
        description="Groq API key for non-blog moderation flows",
    )
    groq_model: str = Field(
        default="openai/gpt-oss-20b",
        validation_alias=AliasChoices("GROQ_MODEL"),
    )
    groq_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GROQ_BASE_URL"),
        description="Optional OpenAI-compatible base URL override for Groq client",
    )
    groq_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    groq_max_tokens: int = Field(default=1000, gt=0)

    blog_deepseek_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("BLOG_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
        description="DeepSeek API key dedicated for blog comment moderation",
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

    # ── Google Cloud Vision ───────────────────────────────────────────────
    google_application_credentials: str | None = None
    google_application_credentials_json: str | None = None

    # ── Worker ───────────────────────────────────────────────────────────
    trigger_mode: Literal["POLL", "OUTBOX", "API"] = "API"
    poll_interval_seconds: int = Field(default=30, gt=0)
    max_concurrent_reviews: int = Field(default=5, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    max_failure_count_before_alert: int = Field(default=5, ge=1)
    blog_comment_retry_interval_minutes: int = Field(default=5, gt=0)
    blog_comment_manual_review_timeout_hours: int = Field(default=24, gt=0)
    blog_comment_lock_days: int = Field(default=7, gt=0)
    blog_comment_violation_threshold: int = Field(default=20, gt=0)

    # ── Image thresholds ─────────────────────────────────────────────────
    image_min_size_kb: int = Field(default=10, gt=0)
    image_max_size_mb: int = Field(default=5, gt=0)
    image_blur_lv_reject_threshold: float = Field(default=1.0, gt=0)

    # ── Business rules ───────────────────────────────────────────────────
    account_rejected_review_days: int = Field(default=30, gt=0)
    account_rejected_review_max: int = Field(default=2, ge=1)
    llm_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)

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
