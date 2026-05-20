"""
app/notification/service.py
----------------------------
Notification service: inserts rows into Notification.Deliveries
when a review is set to ManualReview.
"""

from __future__ import annotations

import json

from app.core.database import get_connection, get_cursor
from app.core.logging import get_logger

logger = get_logger(__name__)

_ROLE_TO_RECIPIENT = {2: "ADMIN", 3: "STAFF"}


class NotificationService:
    async def send_manual_review_alert(
        self,
        review_id: int,
        reason: str,
        admin_staff_accounts: list[dict],
    ) -> int:
        if not admin_staff_accounts:
            logger.warning("No admin/staff accounts found for ManualReview notification")
            return 0

        title = "Cần kiểm duyệt review thủ công"
        inserted = 0

        for account in admin_staff_accounts:
            account_id = account["account_id"]
            role_id = account["role_id"]
            recipient_type = _ROLE_TO_RECIPIENT.get(role_id, "STAFF")
            idempotency_key = f"moderation:review:{review_id}:account:{account_id}"
            message = (
                f"ReviewID #{review_id} cần được kiểm duyệt thủ công. "
                f"Lý do: {reason[:200]}"
            )
            payload = json.dumps({"review_id": review_id, "reason": reason[:200]}, ensure_ascii=False)

            sql = """
                IF NOT EXISTS (
                    SELECT 1 FROM [Notification].[Deliveries]
                    WHERE [IdempotencyKey] = ?
                )
                BEGIN
                    INSERT INTO [Notification].[Deliveries]
                      ([AccountID], [CampaignID], [TemplateCode], [RecipientType],
                       [Channel], [NotificationType], [Title], [Message],
                       [Payload], [Status], [IdempotencyKey], [CreatedAt])
                    VALUES
                      (?, NULL, NULL, ?,
                       'WEB_BELL', 'SYSTEM', ?, ?,
                       ?, 'Unread', ?, GETUTCDATE())
                END
            """
            try:
                async with get_connection() as conn:
                    async with get_cursor(conn) as cur:
                        await cur.execute(
                            sql,
                            idempotency_key, account_id, recipient_type,
                            title, message, payload, idempotency_key,
                        )
                inserted += 1
            except Exception as exc:
                logger.error("Failed to insert notification", review_id=review_id,
                             account_id=account_id, error=str(exc))

        logger.info("ManualReview notifications sent", review_id=review_id,
                    total=inserted, recipients=len(admin_staff_accounts))
        return inserted
