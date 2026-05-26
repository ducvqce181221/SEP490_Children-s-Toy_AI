from __future__ import annotations

from app.features.moderation.blog_comment.repository import BlogCommentModerationRepository
from app.features.moderation.schemas import BlogCommentRecord


class BlogCommentNotificationService:
    def __init__(self) -> None:
        self._repo = BlogCommentModerationRepository()

    async def notify_rejected(self, record: BlogCommentRecord, reason: str) -> None:
        title = "Comment rejected"
        message = f"Your comment was rejected because: {reason}"
        key = f"blog-comment:rejected:{record.target_type.value}:{record.target_id}"
        await self._repo.insert_user_notification(
            account_id=record.account_id,
            title=title,
            message=message,
            idempotency_key=key,
        )

    async def notify_auto_rejected_timeout(self, record: BlogCommentRecord) -> None:
        title = "Comment rejected"
        message = "Your comment was rejected because it was not reviewed within 24 hours."
        key = f"blog-comment:auto-timeout:{record.target_type.value}:{record.target_id}"
        await self._repo.insert_user_notification(
            account_id=record.account_id,
            title=title,
            message=message,
            idempotency_key=key,
        )

    async def notify_account_locked(self, account_id: int) -> None:
        await self._repo.insert_user_notification(
            account_id=account_id,
            title="Commenting locked",
            message="Your commenting access has been locked for 7 days due to repeated violations.",
            idempotency_key=f"blog-comment:lock:{account_id}",
        )

    async def notify_account_unlocked(self, account_id: int) -> None:
        await self._repo.insert_user_notification(
            account_id=account_id,
            title="Commenting unlocked",
            message="Your commenting access has been restored. Please follow the community guidelines.",
            idempotency_key=f"blog-comment:unlock:{account_id}",
        )
