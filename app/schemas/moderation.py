"""
app/schemas/moderation.py
--------------------------
Pydantic models and enums for the moderation domain.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ModerationStatus(StrEnum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    MANUAL_REVIEW = "ManualReview"
    FAILED = "Failed"


class ModerationDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class TargetType(StrEnum):
    TEXT = "Text"
    IMAGE = "Image"


class ReviewRecord(BaseModel):
    review_id: int
    account_id: int
    product_id: int
    order_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = None
    moderation_status: ModerationStatus
    created_at: datetime


class ReviewImageRecord(BaseModel):
    review_product_image_id: int
    review_product_id: int
    image_url: str
    moderation_status: ModerationStatus
    phash: str | None = None


class TextPipelineResult(BaseModel):
    decision: ModerationDecision
    confidence: float = Field(ge=0.0, le=1.0)
    category: str
    flags: list[str] = Field(default_factory=list)
    reason: str
    decided_by: str = "llm"
    raw_llm_result: dict[str, Any] | None = None


class ImagePipelineResult(BaseModel):
    decision: ModerationDecision
    flags: list[str] = Field(default_factory=list)
    reason: str
    decided_by: str = "vision"
    phash: str | None = None
    raw_vision_result: dict[str, Any] | None = None


class ReviewModerationResult(BaseModel):
    review_id: int
    text_result: TextPipelineResult | None = None
    image_results: list[tuple[int, ImagePipelineResult]] = Field(default_factory=list)
    final_decision: ModerationDecision = ModerationDecision.APPROVED


class NotificationPayload(BaseModel):
    account_id: int
    recipient_type: str
    title: str
    message: str
    idempotency_key: str


class BlogCommentTargetType(StrEnum):
    COMMENT = "Comment"
    REPLY = "Reply"


class BlogCommentRecord(BaseModel):
    target_type: BlogCommentTargetType
    target_id: int
    account_id: int
    comment: str | None = None
    moderation_status: ModerationStatus
    retry_count: int = Field(ge=0)
    last_retry_at: datetime | None = None
    created_at: datetime


class BlogCommentReason(BaseModel):
    ban_reason_id: int
    content: str
