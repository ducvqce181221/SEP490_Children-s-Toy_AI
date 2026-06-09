"""
app/integrations/notification.py
---------------------------------
Notification service: inserts rows into Notification.Deliveries
when a review is set to ManualReview or Rejected.
"""

from __future__ import annotations

import json

from app.database.connection import get_connection, get_cursor
from app.core.logging import get_logger

logger = get_logger(__name__)

_ROLE_TO_RECIPIENT = {2: "ADMIN", 3: "STAFF"}


class NotificationService:
    async def send_manual_review_alert(
        self,
        review_id: int,
        reviewer_name: str,
        reason: str,
        admin_staff_accounts: list[dict],
    ) -> int:
        if not admin_staff_accounts:
            logger.warning("No admin/staff accounts found for ManualReview notification")
            return 0

        title = "Manual review required"
        inserted = 0

        for account in admin_staff_accounts:
            account_id = account["account_id"]
            role_id = account["role_id"]
            recipient_type = _ROLE_TO_RECIPIENT.get(role_id, "STAFF")
            idempotency_key = f"moderation:review:{review_id}:account:{account_id}"
            message = (
                f"Customer review by {reviewer_name} requires manual moderation. "
                f"Reason: {reason[:200]}"
            )
            payload = json.dumps({"review_id": review_id, "reason": reason[:200]}, ensure_ascii=False)
            action_target = f"/admin/product-reviews?reviewId={review_id}"

            sql = """
                IF NOT EXISTS (
                    SELECT 1 FROM [Notification].[Deliveries]
                    WHERE [IdempotencyKey] = ?
                )
                BEGIN
                    INSERT INTO [Notification].[Deliveries]
                      ([AccountID], [CampaignID], [TemplateCode], [RecipientType],
                       [Channel], [NotificationType], [Title], [Message],
                       [Payload], [Status], [IdempotencyKey], [ActionTarget], [CreatedAt])
                    VALUES
                      (?, NULL, NULL, ?,
                       'WEB_BELL', 'SYSTEM', ?, ?,
                       ?, 'Unread', ?, ?, GETUTCDATE())
                END
            """
            try:
                async with get_connection() as conn:
                    async with get_cursor(conn) as cur:
                        await cur.execute(
                            sql,
                            idempotency_key, account_id, recipient_type,
                            title, message, payload, idempotency_key, action_target,
                        )
                inserted += 1
            except Exception as exc:
                logger.error("Failed to insert notification", review_id=review_id,
                             account_id=account_id, error=str(exc))

        logger.info("ManualReview notifications sent", review_id=review_id,
                    total=inserted, recipients=len(admin_staff_accounts))
        return inserted

    async def send_customer_rejection_notification(
        self,
        review_id: int,
        customer_id: int,
        reason: str,
    ) -> bool:
        title = "Your review was not approved"
        idempotency_key = f"moderation:review:{review_id}:rejected"
        message = (
            f"Your product review was not approved due to content policy violation: {reason[:200]}"
        )
        payload = json.dumps({"review_id": review_id, "reason": reason[:200]}, ensure_ascii=False)
        action_target = "/profile/reviews"

        sql = """
            IF NOT EXISTS (
                SELECT 1 FROM [Notification].[Deliveries]
                WHERE [IdempotencyKey] = ?
            )
            BEGIN
                INSERT INTO [Notification].[Deliveries]
                  ([AccountID], [CampaignID], [TemplateCode], [RecipientType],
                   [Channel], [NotificationType], [Title], [Message],
                   [Payload], [Status], [IdempotencyKey], [ActionTarget], [CreatedAt])
                VALUES
                  (?, NULL, NULL, 'CUSTOMER',
                   'WEB_BELL', 'SYSTEM', ?, ?,
                   ?, 'Unread', ?, ?, GETUTCDATE())
            END
        """
        try:
            async with get_connection() as conn:
                async with get_cursor(conn) as cur:
                    await cur.execute(
                        sql,
                        idempotency_key, customer_id,
                        title, message, payload, idempotency_key, action_target,
                    )
            logger.info("Customer rejection notification successfully scheduled", review_id=review_id, customer_id=customer_id)
            return True
        except Exception as exc:
            logger.error("Failed to insert customer rejection notification", review_id=review_id,
                         customer_id=customer_id, error=str(exc))
            return False
