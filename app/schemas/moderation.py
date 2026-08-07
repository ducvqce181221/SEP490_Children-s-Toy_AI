"""
app/schemas/moderation.py
--------------------------
Định nghĩa các Pydantic Data Models và Enums cho hệ thống kiểm duyệt AI (Moderation Domain).
Bao gồm kiểm duyệt đánh giá sản phẩm và kiểm duyệt bình luận / phản hồi Blog.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ModerationStatus(StrEnum):
    """Enum các trạng thái kiểm duyệt của một đối tượng trong cơ sở dữ liệu."""
    PENDING = "Pending"  # Chờ kiểm duyệt
    PROCESSING = "Processing"  # Đang trong quá trình xử lý AI
    APPROVED = "Approved"  # Đã được tự động duyệt hiển thị
    REJECTED = "Rejected"  # Đã bị từ chối/bắt lỗi vi phạm
    MANUAL_REVIEW = "ManualReview"  # Chờ người quản trị (Admin) xem xét và quyết định thủ công
    FAILED = "Failed"  # Gặp sự cố hệ thống/AI không phản hồi sau nhiều lần thử lại


class ModerationDecision(StrEnum):
    """Enum quyết định phân loại từ AI Engine."""
    APPROVED = "APPROVED"  # Chấp nhận duyệt
    REJECTED = "REJECTED"  # Từ chối vi phạm
    MANUAL_REVIEW = "MANUAL_REVIEW"  # Chuyển kiểm duyệt tay


class TargetType(StrEnum):
    """Loại đối tượng kiểm duyệt chung (Văn bản hoặc Hình ảnh)."""
    TEXT = "Text"
    IMAGE = "Image"


class ReviewRecord(BaseModel):
    """Bản ghi đánh giá sản phẩm trong CSDL."""
    review_id: int
    account_id: int
    product_id: int
    order_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = None
    moderation_status: ModerationStatus
    created_at: datetime


class ReviewImageRecord(BaseModel):
    """Bản ghi hình ảnh đánh giá sản phẩm."""
    review_product_image_id: int
    review_product_id: int
    image_url: str
    moderation_status: ModerationStatus


class TextPipelineResult(BaseModel):
    """Kết quả đầu ra từ Pipeline kiểm duyệt văn bản của AI."""
    decision: ModerationDecision  # Quyết định: APPROVED, REJECTED, MANUAL_REVIEW
    confidence: float = Field(ge=0.0, le=1.0)  # Điểm số tin cậy của AI (0.0 đến 1.0)
    category: str  # Phân loại danh mục (vd: "clean", "spam", "offensive", "privacy", v.v.)
    flags: list[str] = Field(default_factory=list)  # Danh sách cờ phát hiện vi phạm
    reason: str  # Lý do hoặc giải thích bằng tiếng Anh
    decided_by: str = "llm"  # Đơn vị đưa ra quyết định ("llm", "prefilter", "post_processor", v.v.)
    raw_llm_result: dict[str, Any] | None = None  # Phản hồi JSON gốc từ LLM


class ImagePipelineResult(BaseModel):
    """Kết quả kiểm duyệt hình ảnh."""
    decision: ModerationDecision
    flags: list[str] = Field(default_factory=list)
    reason: str
    decided_by: str = "vision"
    raw_vision_result: dict[str, Any] | None = None


class ReviewModerationResult(BaseModel):
    """Kết quả kiểm duyệt tổng hợp cho 1 đánh giá sản phẩm (bao gồm cả văn bản và danh sách hình ảnh)."""
    review_id: int
    text_result: TextPipelineResult | None = None
    image_results: list[tuple[int, ImagePipelineResult]] = Field(default_factory=list)
    final_decision: ModerationDecision = ModerationDecision.APPROVED


class NotificationPayload(BaseModel):
    """Payload dữ liệu gửi thông báo cho người dùng."""
    account_id: int
    recipient_type: str
    title: str
    message: str
    idempotency_key: str


class BlogCommentTargetType(StrEnum):
    """Enum phân biệt loại đối tượng bình luận Blog: Bình luận gốc (Comment) hoặc Phản hồi bình luận (Reply)."""
    COMMENT = "Comment"
    REPLY = "Reply"


class BlogCommentRecord(BaseModel):
    """Model đại diện cho 1 bản ghi bình luận hoặc phản hồi Blog trong CSDL SQL Server."""
    target_type: BlogCommentTargetType  # Loại: Comment hoặc Reply
    target_id: int  # ID của ReviewBlogID hoặc ReplyBlogID
    account_id: int  # ID tài khoản tác giả bình luận
    comment: str | None = None  # Nội dung bình luận
    moderation_status: ModerationStatus  # Trạng thái kiểm duyệt hiện tại
    retry_count: int = Field(ge=0)  # Số lần đã thử lại khi gặp lỗi
    last_retry_at: datetime | None = None  # Mốc thời gian thử lại gần nhất
    created_at: datetime  # Thời điểm tạo bình luận


class BlogCommentReason(BaseModel):
    """Model đại diện cho lý do từ chối bình luận trong bảng [dbo].[BlogCommentBanReasons]."""
    ban_reason_id: int  # ID lý do cấm trong CSDL
    content: str  # Nội dung mô tả lý do cấm

