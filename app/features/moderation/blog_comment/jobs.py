from __future__ import annotations

from app.core.logging import get_logger
from app.features.moderation.blog_comment.notification_service import BlogCommentNotificationService
from app.features.moderation.blog_comment.repository import BlogCommentModerationRepository
from app.features.moderation.schemas import ModerationStatus
from app.features.moderation.blog_comment.violation_service import BlogCommentViolationService

logger = get_logger(__name__)


async def run_auto_reject_manual_review_timeout_job() -> int:
    repo = BlogCommentModerationRepository()
    notif = BlogCommentNotificationService()
    violation = BlogCommentViolationService()

    comments = await repo.get_expired_manual_review_comments()
    replies = await repo.get_expired_manual_review_replies()
    expired = comments + replies

    for record in expired:
        await repo.update_target_status(
            target_type=record.target_type,
            target_id=record.target_id,
            status=ModerationStatus.REJECTED,
        )
        await repo.insert_moderation_log(
            record=record,
            action="Rejected",
            moderator_type="SYSTEM",
            moderation_result={"reason": "manual_review_timeout_24h"},
        )
        await notif.notify_auto_rejected_timeout(record)
        await violation.register_violation_and_lock_if_needed(record.account_id)

    if expired:
        logger.info("Auto reject timeout job processed", count=len(expired))
    return len(expired)


async def run_auto_unlock_comment_accounts_job() -> int:
    repo = BlogCommentModerationRepository()
    notif = BlogCommentNotificationService()
    account_ids = await repo.get_accounts_to_unlock()
    for account_id in account_ids:
        await repo.unlock_comment_privilege(account_id)
        await notif.notify_account_unlocked(account_id)
    if account_ids:
        logger.info("Auto unlock comment accounts job processed", count=len(account_ids))
    return len(account_ids)

