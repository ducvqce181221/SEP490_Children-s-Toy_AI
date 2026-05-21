from __future__ import annotations

from app.core.config import get_settings


class BlogCommentRetryPolicy:
    def __init__(self) -> None:
        settings = get_settings()
        self.max_attempts = settings.max_retry_attempts
        self.retry_interval_minutes = settings.blog_comment_retry_interval_minutes

    def should_fail(self, retry_count: int) -> bool:
        return retry_count >= self.max_attempts

