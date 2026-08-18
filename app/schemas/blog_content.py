"""
app/schemas/blog_content.py
----------------------------
Định nghĩa các Pydantic Schema và Data Models cho miền tính năng Sinh bài viết Blog bằng AI (Blog Content Generation).
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class BlogContentGenerateRequest(BaseModel):
    """Schema Pydantic cho dữ liệu yêu cầu sinh bài viết Blog bằng AI gửi từ Backend/Admin."""
    action: Literal["Generate", "Improve", "Rewrite"] = "Generate"  # Hành động: Tạo mới / Cải thiện / Viết lại
    title: str = Field(min_length=1, max_length=255)  # Tiêu đề bài viết đầu vào (bắt buộc)
    description: str | None = None  # Mô tả ngắn hoặc tóm tắt ý định (tùy chọn)
    promptStructure: str = Field(min_length=1, max_length=5000)  # Cấu trúc dàn ý hoặc gợi ý nội dung (bắt buộc)
    defaultTone: str = Field(default="Friendly", min_length=1, max_length=50)  # Tone giọng bài viết (Mặc định: Friendly)
    defaultCategoryId: int = Field(gt=0)  # ID danh mục đồ chơi/bài viết (bắt buộc > 0)
    sourceContent: str | None = None  # Văn bản nội dung nguồn hiện tại (dùng khi Improve/Rewrite)


class BlogContentGenerateResponse(BaseModel):
    """Schema phản hồi khi AI sinh thành công bài viết Blog."""
    title: str  # Tiêu đề bài viết tiếng Anh đã được AI viết lại/chuẩn hóa
    content: str  # Nội dung bài viết định dạng HTML hoàn chỉnh (chuẩn SEO, đủ 3.000-6.000 ký tự)


class BlogContentBlockedResponse(BaseModel):
    """Schema phản hồi khi yêu cầu sinh bài viết bị AI hệ thống từ chối/chặn vì lý do an toàn hoặc lạc đề."""
    status: Literal["blocked"] = "blocked"  # Trạng thái luôn là "blocked"
    violation_type: Literal["brand_external", "topic_restricted", "out_of_scope", "unsafe_content"]  # Loại vi phạm
    violated_keyword: str  # Từ khóa hoặc lý do gây ra vi phạm
    reason: str  # Mô tả ngắn lý do bị chặn
    suggestions: list[str]  # Danh sách 4 gợi ý tiêu đề/chủ đề thay thế hợp lệ


# Response type chung cho endpoint sinh bài viết Blog: Có thể là Response thành công hoặc Response bị chặn
BlogContentGenerateEndpointResponse = Union[BlogContentGenerateResponse, BlogContentBlockedResponse]

