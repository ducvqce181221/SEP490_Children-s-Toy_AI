from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class BlogCommentStatus(StrEnum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    MANUAL_REVIEW = "ManualReview"
    FAILED = "Failed"


class BlogCommentTargetType(StrEnum):
    COMMENT = "Comment"
    REPLY = "Reply"


class BlogCommentDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class BlogCommentRecord(BaseModel):
    target_type: BlogCommentTargetType
    target_id: int
    account_id: int
    comment: str | None = None
    moderation_status: BlogCommentStatus
    retry_count: int = Field(ge=0)
    last_retry_at: datetime | None = None
    created_at: datetime


class BlogCommentReason(BaseModel):
    ban_reason_id: int
    content: str


class BlogCommentAiResult(BaseModel):
    decision: BlogCommentDecision
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason_text: str
    flags: list[str] = Field(default_factory=list)
    raw: dict[str, object] = Field(default_factory=dict)

