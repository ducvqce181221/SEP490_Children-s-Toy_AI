"""
app/repositories/product_review.py
----------------------------------
Database access layer for the product review moderation feature.
All SQL against SQL Server via aioodbc. No ORM.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.connection import get_connection, get_cursor
from app.core.logging import get_logger
from app.schemas.moderation import (
    ModerationStatus, ReviewImageRecord, ReviewRecord,
)

logger = get_logger(__name__)


class ModerationRepository:

    async def fetch_pending_reviews(self, batch_size: int = 20) -> list[ReviewRecord]:
        sql = f"""
            UPDATE TOP ({int(batch_size)}) rp
            SET rp.[ModerationStatus] = 'Processing',
                rp.[UpdatedAt] = GETUTCDATE()
            OUTPUT
                INSERTED.[ReviewID], INSERTED.[AccountID], INSERTED.[ProductID],
                INSERTED.[OrderID], INSERTED.[Rating], INSERTED.[Comment],
                INSERTED.[ModerationStatus], INSERTED.[CreatedAt]
            FROM [dbo].[ReviewProducts] rp WITH (ROWLOCK, READPAST)
            WHERE rp.[ModerationStatus] = 'Pending'
              AND rp.[IsDeleted] = 0
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        return [
            ReviewRecord(
                review_id=row[0], account_id=row[1], product_id=row[2],
                order_id=row[3], rating=row[4], comment=row[5],
                moderation_status=ModerationStatus(row[6]), created_at=row[7],
            )
            for row in rows
        ]

    async def fetch_images_for_review(self, review_id: int) -> list[ReviewImageRecord]:
        sql = """
            SELECT [ReviewProductImageID], [ReviewProductID], [ImageURL],
                   [ModerationStatus], [PHash]
            FROM [dbo].[ReviewProductImages]
            WHERE [ReviewProductID] = ? AND [IsDeleted] = 0
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, review_id)
                rows = await cur.fetchall()
        return [
            ReviewImageRecord(
                review_product_image_id=row[0], review_product_id=row[1],
                image_url=row[2], moderation_status=ModerationStatus(row[3]), phash=row[4],
            )
            for row in rows
        ]

    async def get_recent_rejected_count(self, account_id: int, days: int) -> int:
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        sql = """
            SELECT COUNT(*) FROM [dbo].[ReviewProducts]
            WHERE [AccountID] = ? AND [ModerationStatus] = 'Rejected'
              AND [IsDeleted] = 0 AND [UpdatedAt] >= ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, account_id, since)
                row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def update_review_status(self, review_id: int, status: ModerationStatus) -> None:
        sql = """
            UPDATE [dbo].[ReviewProducts]
            SET [ModerationStatus] = ?, [UpdatedAt] = GETUTCDATE()
            WHERE [ReviewID] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, status.value, review_id)

    async def update_image_status(self, image_id: int, status: ModerationStatus, phash: str | None = None) -> None:
        if phash is not None:
            sql = """
                UPDATE [dbo].[ReviewProductImages]
                SET [ModerationStatus] = ?, [PHash] = ?, [UpdatedAt] = GETUTCDATE()
                WHERE [ReviewProductImageID] = ?
            """
            async with get_connection() as conn:
                async with get_cursor(conn) as cur:
                    await cur.execute(sql, status.value, phash, image_id)
        else:
            sql = """
                UPDATE [dbo].[ReviewProductImages]
                SET [ModerationStatus] = ?, [UpdatedAt] = GETUTCDATE()
                WHERE [ReviewProductImageID] = ?
            """
            async with get_connection() as conn:
                async with get_cursor(conn) as cur:
                    await cur.execute(sql, status.value, image_id)

    async def insert_moderation_log(
        self,
        review_id: int,
        image_id: int | None,
        target_type: str,
        action: str,
        reason: str | None,
        moderation_result: dict[str, Any] | None,
        ai_model_version: str | None = None,
    ) -> None:
        result_json = json.dumps(moderation_result, ensure_ascii=False) if moderation_result else None
        sql = """
            INSERT INTO [dbo].[ReviewModerationLogs]
              ([TargetType], [ReviewID], [ImageID], [ModeratorType],
               [ModeratedBy], [Action], [AIModelVersion], [ModerationResult], [Reason], [CreatedAt])
            VALUES (?, ?, ?, 'AI', NULL, ?, ?, ?, ?, GETUTCDATE())
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(
                    sql, target_type, review_id, image_id,
                    action, ai_model_version, result_json, (reason or "")[:500],
                )

    async def get_failure_count(self, review_id: int) -> int:
        sql = """
            SELECT COUNT(*) FROM [dbo].[ReviewModerationLogs]
            WHERE [ReviewID] = ? AND [ModeratorType] = 'AI'
              AND [Action] = 'ManualReview'
              AND [ModerationResult] LIKE '%llm_call_failed%'
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, review_id)
                row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def fetch_admin_staff_accounts(self) -> list[dict[str, Any]]:
        sql = """
            SELECT [AccountID], [RoleID] FROM [dbo].[Accounts]
            WHERE [RoleID] IN (2, 3) AND [IsActive] = 1 AND [IsDeleted] = 0
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        return [{"account_id": row[0], "role_id": row[1]} for row in rows]

    async def get_reviewer_name_by_review_id(self, review_id: int) -> str:
        sql = """
            SELECT a.[AccountName]
            FROM [dbo].[ReviewProducts] rp
            JOIN [dbo].[Accounts] a ON rp.[AccountID] = a.[AccountID]
            WHERE rp.[ReviewID] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, review_id)
                row = await cur.fetchone()
        return row[0] if row else "Customer"

    async def update_review_comment(self, review_id: int, comment: str) -> None:
        sql = """
            UPDATE [dbo].[ReviewProducts]
            SET [Comment] = ?, [UpdatedAt] = GETUTCDATE()
            WHERE [ReviewID] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, comment, review_id)

    async def get_review_moderation_stats(self) -> dict[str, int]:
        sql = """
            SELECT [ModerationStatus], COUNT(*) AS cnt
            FROM [dbo].[ReviewProducts]
            WHERE [IsDeleted] = 0
            GROUP BY [ModerationStatus]
        """
        counts: dict[str, int] = {
            "Pending": 0,
            "Processing": 0,
            "Approved": 0,
            "Rejected": 0,
            "ManualReview": 0,
        }
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        for row in rows:
            status, count = row[0], row[1]
            if status in counts:
                counts[status] = count
        return counts

