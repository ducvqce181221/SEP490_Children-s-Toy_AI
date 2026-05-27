from __future__ import annotations

from app.core.config import get_settings
from app.features.moderation.blog_comment.notification_service import BlogCommentNotificationService
from app.features.moderation.blog_comment.repository import BlogCommentModerationRepository


class BlogCommentViolationService:
    def __init__(self) -> None:
        self._repo = BlogCommentModerationRepository()
        self._notif = BlogCommentNotificationService()
        self._settings = get_settings()

    async def register_violation_and_lock_if_needed(self, account_id: int) -> None:
        count = await self._repo.increment_violation(account_id)
        if count < self._settings.blog_comment_violation_threshold:
            return
        await self._repo.lock_comment_privilege(account_id)
        await self._notif.notify_account_locked(account_id)

