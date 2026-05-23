from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.database import get_connection, get_cursor
from app.features.moderation.blog_comment.schemas import (
    BlogCommentReason,
    BlogCommentRecord,
    BlogCommentStatus,
    BlogCommentTargetType,
)


class BlogCommentModerationRepository:
    async def claim_target_for_immediate_moderation(
        self,
        *,
        target_type: BlogCommentTargetType,
        target_id: int,
    ) -> BlogCommentRecord | None:
        if target_type == BlogCommentTargetType.COMMENT:
            return await self._claim_one_review_blog(target_id)
        return await self._claim_one_review_blog_reply(target_id)

    async def _claim_one_review_blog(self, target_id: int) -> BlogCommentRecord | None:
        sql = """
            SET NOCOUNT ON;

            DECLARE @claimed TABLE (
                [ReviewBlogID] BIGINT,
                [AccountID] BIGINT,
                [Comment] NVARCHAR(MAX),
                [ModerationStatus] NVARCHAR(50),
                [RetryCount] INT,
                [LastRetryAt] DATETIME2,
                [CreatedAt] DATETIME2
            );

            UPDATE [dbo].[ReviewBlogs]
            SET [ModerationStatus] = 'Processing',
                [UpdatedAt] = GETUTCDATE()
            OUTPUT
                INSERTED.[ReviewBlogID],
                INSERTED.[AccountID],
                INSERTED.[Comment],
                INSERTED.[ModerationStatus],
                INSERTED.[RetryCount],
                INSERTED.[LastRetryAt],
                INSERTED.[CreatedAt]
            INTO @claimed
            WHERE [ReviewBlogID] = ?
              AND [IsDeleted] = 0
              AND [ModerationStatus] = 'Pending';

            SELECT
                [ReviewBlogID],
                [AccountID],
                [Comment],
                [ModerationStatus],
                [RetryCount],
                [LastRetryAt],
                [CreatedAt]
            FROM @claimed;
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, target_id)
                row = await cur.fetchone()
        if not row:
            return None
        return BlogCommentRecord(
            target_type=BlogCommentTargetType.COMMENT,
            target_id=row[0],
            account_id=row[1],
            comment=row[2],
            moderation_status=BlogCommentStatus(row[3]),
            retry_count=int(row[4] or 0),
            last_retry_at=row[5],
            created_at=row[6],
        )

    async def _claim_one_review_blog_reply(self, target_id: int) -> BlogCommentRecord | None:
        sql = """
            SET NOCOUNT ON;

            DECLARE @claimed TABLE (
                [ReplyBlogID] BIGINT,
                [AccountID] BIGINT,
                [Comment] NVARCHAR(MAX),
                [ModerationStatus] NVARCHAR(50),
                [RetryCount] INT,
                [LastRetryAt] DATETIME2,
                [CreatedAt] DATETIME2
            );

            UPDATE [dbo].[ReviewBlogReplies]
            SET [ModerationStatus] = 'Processing',
                [UpdatedAt] = GETUTCDATE()
            OUTPUT
                INSERTED.[ReplyBlogID],
                INSERTED.[AccountID],
                INSERTED.[Comment],
                INSERTED.[ModerationStatus],
                INSERTED.[RetryCount],
                INSERTED.[LastRetryAt],
                INSERTED.[CreatedAt]
            INTO @claimed
            WHERE [ReplyBlogID] = ?
              AND [IsDeleted] = 0
              AND [ModerationStatus] = 'Pending';

            SELECT
                [ReplyBlogID],
                [AccountID],
                [Comment],
                [ModerationStatus],
                [RetryCount],
                [LastRetryAt],
                [CreatedAt]
            FROM @claimed;
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, target_id)
                row = await cur.fetchone()
        if not row:
            return None
        return BlogCommentRecord(
            target_type=BlogCommentTargetType.REPLY,
            target_id=row[0],
            account_id=row[1],
            comment=row[2],
            moderation_status=BlogCommentStatus(row[3]),
            retry_count=int(row[4] or 0),
            last_retry_at=row[5],
            created_at=row[6],
        )

    async def get_target_status(
        self,
        *,
        target_type: BlogCommentTargetType,
        target_id: int,
    ) -> str | None:
        if target_type == BlogCommentTargetType.COMMENT:
            sql = """
                SELECT [ModerationStatus]
                FROM [dbo].[ReviewBlogs]
                WHERE [ReviewBlogID] = ? AND [IsDeleted] = 0
            """
        else:
            sql = """
                SELECT [ModerationStatus]
                FROM [dbo].[ReviewBlogReplies]
                WHERE [ReplyBlogID] = ? AND [IsDeleted] = 0
            """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, target_id)
                row = await cur.fetchone()
        return str(row[0]) if row else None

    async def claim_pending_comments(
        self,
        *,
        batch_size: int,
        retry_interval_minutes: int,
    ) -> list[BlogCommentRecord]:
        now = datetime.now(tz=timezone.utc)
        retry_due = now - timedelta(minutes=retry_interval_minutes)
        comment_batch = max(1, batch_size // 2)
        reply_batch = max(1, batch_size - comment_batch)
        claimed: list[BlogCommentRecord] = []

        claimed.extend(await self._claim_review_blogs(comment_batch, retry_due))
        claimed.extend(await self._claim_review_blog_replies(reply_batch, retry_due))
        return claimed

    async def _claim_review_blogs(
        self,
        batch_size: int,
        retry_due: datetime,
    ) -> list[BlogCommentRecord]:
        sql = f"""
            SET NOCOUNT ON;

            DECLARE @claimed TABLE (
                [ReviewBlogID] BIGINT,
                [AccountID] BIGINT,
                [Comment] NVARCHAR(MAX),
                [ModerationStatus] NVARCHAR(50),
                [RetryCount] INT,
                [LastRetryAt] DATETIME2,
                [CreatedAt] DATETIME2
            );

            UPDATE TOP ({int(batch_size)}) rb
            SET rb.[ModerationStatus] = 'Processing',
                rb.[UpdatedAt] = GETUTCDATE()
            OUTPUT
                INSERTED.[ReviewBlogID],
                INSERTED.[AccountID],
                INSERTED.[Comment],
                INSERTED.[ModerationStatus],
                INSERTED.[RetryCount],
                INSERTED.[LastRetryAt],
                INSERTED.[CreatedAt]
            INTO @claimed
            FROM [dbo].[ReviewBlogs] rb WITH (ROWLOCK, READPAST)
            WHERE rb.[IsDeleted] = 0
              AND rb.[ModerationStatus] = 'Pending'
              AND (rb.[LastRetryAt] IS NULL OR rb.[LastRetryAt] <= ?);

            SELECT
                [ReviewBlogID],
                [AccountID],
                [Comment],
                [ModerationStatus],
                [RetryCount],
                [LastRetryAt],
                [CreatedAt]
            FROM @claimed;
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, retry_due)
                rows = await cur.fetchall()
        return [
            BlogCommentRecord(
                target_type=BlogCommentTargetType.COMMENT,
                target_id=row[0],
                account_id=row[1],
                comment=row[2],
                moderation_status=BlogCommentStatus(row[3]),
                retry_count=int(row[4] or 0),
                last_retry_at=row[5],
                created_at=row[6],
            )
            for row in rows
        ]

    async def _claim_review_blog_replies(
        self,
        batch_size: int,
        retry_due: datetime,
    ) -> list[BlogCommentRecord]:
        sql = f"""
            SET NOCOUNT ON;

            DECLARE @claimed TABLE (
                [ReplyBlogID] BIGINT,
                [AccountID] BIGINT,
                [Comment] NVARCHAR(MAX),
                [ModerationStatus] NVARCHAR(50),
                [RetryCount] INT,
                [LastRetryAt] DATETIME2,
                [CreatedAt] DATETIME2
            );

            UPDATE TOP ({int(batch_size)}) rr
            SET rr.[ModerationStatus] = 'Processing',
                rr.[UpdatedAt] = GETUTCDATE()
            OUTPUT
                INSERTED.[ReplyBlogID],
                INSERTED.[AccountID],
                INSERTED.[Comment],
                INSERTED.[ModerationStatus],
                INSERTED.[RetryCount],
                INSERTED.[LastRetryAt],
                INSERTED.[CreatedAt]
            INTO @claimed
            FROM [dbo].[ReviewBlogReplies] rr WITH (ROWLOCK, READPAST)
            WHERE rr.[IsDeleted] = 0
              AND rr.[ModerationStatus] = 'Pending'
              AND (rr.[LastRetryAt] IS NULL OR rr.[LastRetryAt] <= ?);

            SELECT
                [ReplyBlogID],
                [AccountID],
                [Comment],
                [ModerationStatus],
                [RetryCount],
                [LastRetryAt],
                [CreatedAt]
            FROM @claimed;
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, retry_due)
                rows = await cur.fetchall()
        return [
            BlogCommentRecord(
                target_type=BlogCommentTargetType.REPLY,
                target_id=row[0],
                account_id=row[1],
                comment=row[2],
                moderation_status=BlogCommentStatus(row[3]),
                retry_count=int(row[4] or 0),
                last_retry_at=row[5],
                created_at=row[6],
            )
            for row in rows
        ]

    async def get_reason_by_content(self, content: str) -> BlogCommentReason | None:
        sql = """
            SELECT TOP 1 [BanReasonID], [Content]
            FROM [dbo].[BlogCommentBanReasons]
            WHERE [Content] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, content)
                row = await cur.fetchone()
        if not row:
            return None
        return BlogCommentReason(ban_reason_id=int(row[0]), content=str(row[1]))

    async def get_default_rejection_reason(self) -> BlogCommentReason | None:
        sql = """
            SELECT TOP 1 [BanReasonID], [Content]
            FROM [dbo].[BlogCommentBanReasons]
            ORDER BY
                CASE WHEN [Content] = N'Content unsuitable for children' THEN 0 ELSE 1 END,
                [BanReasonID]
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql)
                row = await cur.fetchone()
        if not row:
            return None
        return BlogCommentReason(ban_reason_id=int(row[0]), content=str(row[1]))

    async def update_target_status(
        self,
        *,
        target_type: BlogCommentTargetType,
        target_id: int,
        status: BlogCommentStatus,
        retry_count: int | None = None,
        manual_review_deadline_hours: int | None = None,
    ) -> None:
        if target_type == BlogCommentTargetType.COMMENT:
            await self._update_review_blog(
                target_id=target_id,
                status=status,
                retry_count=retry_count,
                manual_review_deadline_hours=manual_review_deadline_hours,
            )
            return
        await self._update_review_blog_reply(
            target_id=target_id,
            status=status,
            retry_count=retry_count,
            manual_review_deadline_hours=manual_review_deadline_hours,
        )

    async def _update_review_blog(
        self,
        *,
        target_id: int,
        status: BlogCommentStatus,
        retry_count: int | None,
        manual_review_deadline_hours: int | None,
    ) -> None:
        deadline_sql = "DATEADD(HOUR, ?, GETUTCDATE())" if manual_review_deadline_hours else "NULL"
        if retry_count is None:
            sql = f"""
                UPDATE [dbo].[ReviewBlogs]
                SET [ModerationStatus] = ?,
                    [ManualReviewDeadline] = {deadline_sql},
                    [UpdatedAt] = GETUTCDATE()
                WHERE [ReviewBlogID] = ?
            """
            params: list[Any] = [status.value]
            if manual_review_deadline_hours:
                params.append(manual_review_deadline_hours)
            params.append(target_id)
        else:
            sql = f"""
                UPDATE [dbo].[ReviewBlogs]
                SET [ModerationStatus] = ?,
                    [RetryCount] = ?,
                    [LastRetryAt] = GETUTCDATE(),
                    [ManualReviewDeadline] = {deadline_sql},
                    [UpdatedAt] = GETUTCDATE()
                WHERE [ReviewBlogID] = ?
            """
            params = [status.value, retry_count]
            if manual_review_deadline_hours:
                params.append(manual_review_deadline_hours)
            params.append(target_id)
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, *params)

    async def _update_review_blog_reply(
        self,
        *,
        target_id: int,
        status: BlogCommentStatus,
        retry_count: int | None,
        manual_review_deadline_hours: int | None,
    ) -> None:
        deadline_sql = "DATEADD(HOUR, ?, GETUTCDATE())" if manual_review_deadline_hours else "NULL"
        if retry_count is None:
            sql = f"""
                UPDATE [dbo].[ReviewBlogReplies]
                SET [ModerationStatus] = ?,
                    [ManualReviewDeadline] = {deadline_sql},
                    [UpdatedAt] = GETUTCDATE()
                WHERE [ReplyBlogID] = ?
            """
            params: list[Any] = [status.value]
            if manual_review_deadline_hours:
                params.append(manual_review_deadline_hours)
            params.append(target_id)
        else:
            sql = f"""
                UPDATE [dbo].[ReviewBlogReplies]
                SET [ModerationStatus] = ?,
                    [RetryCount] = ?,
                    [LastRetryAt] = GETUTCDATE(),
                    [ManualReviewDeadline] = {deadline_sql},
                    [UpdatedAt] = GETUTCDATE()
                WHERE [ReplyBlogID] = ?
            """
            params = [status.value, retry_count]
            if manual_review_deadline_hours:
                params.append(manual_review_deadline_hours)
            params.append(target_id)
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, *params)

    async def insert_moderation_log(
        self,
        *,
        record: BlogCommentRecord,
        action: str,
        moderator_type: str,
        ban_reason_id: int | None = None,
        confidence_score: float | None = None,
        moderation_result: dict[str, object] | None = None,
    ) -> None:
        result_json = json.dumps(moderation_result, ensure_ascii=False) if moderation_result else None
        sql = """
            INSERT INTO [dbo].[BlogCommentModerationLogs]
              ([TargetType], [CommentID], [ReplyID], [ModeratorType], [ModeratedBy],
               [Action], [BanReasonID], [ConfidenceScore], [ModerationResult], [CreatedAt])
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, GETUTCDATE())
        """
        comment_id = record.target_id if record.target_type == BlogCommentTargetType.COMMENT else None
        reply_id = record.target_id if record.target_type == BlogCommentTargetType.REPLY else None
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(
                    sql,
                    record.target_type.value,
                    comment_id,
                    reply_id,
                    moderator_type,
                    action,
                    ban_reason_id,
                    confidence_score,
                    result_json,
                )

    async def get_or_create_violation_count(self, account_id: int) -> int:
        select_sql = """
            SELECT [ViolationCount]
            FROM [dbo].[BlogCommentViolationCount]
            WHERE [AccountID] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(select_sql, account_id)
                row = await cur.fetchone()
                if row:
                    return int(row[0] or 0)
        insert_sql = """
            INSERT INTO [dbo].[BlogCommentViolationCount]
              ([AccountID], [ViolationCount], [LastViolatedAt], [UpdatedAt], [IsCommentBanned],
               [BannedAt], [BanExpiresAt], [UnbannedAt], [UnbannedBy], [RateCount], [RateWindowAt])
            VALUES (?, 0, NULL, GETUTCDATE(), 0, NULL, NULL, NULL, NULL, 0, NULL)
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(insert_sql, account_id)
        return 0

    async def increment_violation(self, account_id: int) -> int:
        await self.get_or_create_violation_count(account_id)
        sql = """
            SET NOCOUNT ON;

            UPDATE [dbo].[BlogCommentViolationCount]
            SET [ViolationCount] = CASE WHEN [ViolationCount] < 255 THEN [ViolationCount] + 1 ELSE [ViolationCount] END,
                [LastViolatedAt] = GETUTCDATE(),
                [UpdatedAt] = GETUTCDATE()
            WHERE [AccountID] = ?;

            SELECT [ViolationCount]
            FROM [dbo].[BlogCommentViolationCount]
            WHERE [AccountID] = ?;
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, account_id, account_id)
                row = await cur.fetchone()
        return int(row[0] if row else 0)

    async def count_violations_in_window(self, account_id: int, *, days: int) -> int:
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        sql = """
            SELECT COUNT(*)
            FROM [dbo].[BlogCommentModerationLogs]
            WHERE [Action] = 'Rejected'
              AND [CreatedAt] >= ?
              AND (
                    [CommentID] IN (SELECT [ReviewBlogID] FROM [dbo].[ReviewBlogs] WHERE [AccountID] = ?)
                 OR [ReplyID]   IN (SELECT [ReplyBlogID] FROM [dbo].[ReviewBlogReplies] WHERE [AccountID] = ?)
              )
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, since, account_id, account_id)
                row = await cur.fetchone()
        return int(row[0] if row else 0)

    async def lock_comment_privilege(self, account_id: int, *, lock_days: int) -> None:
        await self.get_or_create_violation_count(account_id)
        sql = """
            UPDATE [dbo].[BlogCommentViolationCount]
            SET [IsCommentBanned] = 1,
                [BannedAt] = GETUTCDATE(),
                [BanExpiresAt] = DATEADD(DAY, ?, GETUTCDATE()),
                [UpdatedAt] = GETUTCDATE()
            WHERE [AccountID] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, lock_days, account_id)

    async def get_expired_manual_review_comments(self) -> list[BlogCommentRecord]:
        sql = """
            SELECT [ReviewBlogID], [AccountID], [Comment], [ModerationStatus], [RetryCount], [LastRetryAt], [CreatedAt]
            FROM [dbo].[ReviewBlogs]
            WHERE [IsDeleted] = 0
              AND [ModerationStatus] = 'ManualReview'
              AND [ManualReviewDeadline] IS NOT NULL
              AND [ManualReviewDeadline] <= GETUTCDATE()
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        return [
            BlogCommentRecord(
                target_type=BlogCommentTargetType.COMMENT,
                target_id=row[0],
                account_id=row[1],
                comment=row[2],
                moderation_status=BlogCommentStatus(row[3]),
                retry_count=int(row[4] or 0),
                last_retry_at=row[5],
                created_at=row[6],
            )
            for row in rows
        ]

    async def get_expired_manual_review_replies(self) -> list[BlogCommentRecord]:
        sql = """
            SELECT [ReplyBlogID], [AccountID], [Comment], [ModerationStatus], [RetryCount], [LastRetryAt], [CreatedAt]
            FROM [dbo].[ReviewBlogReplies]
            WHERE [IsDeleted] = 0
              AND [ModerationStatus] = 'ManualReview'
              AND [ManualReviewDeadline] IS NOT NULL
              AND [ManualReviewDeadline] <= GETUTCDATE()
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        return [
            BlogCommentRecord(
                target_type=BlogCommentTargetType.REPLY,
                target_id=row[0],
                account_id=row[1],
                comment=row[2],
                moderation_status=BlogCommentStatus(row[3]),
                retry_count=int(row[4] or 0),
                last_retry_at=row[5],
                created_at=row[6],
            )
            for row in rows
        ]

    async def get_accounts_to_unlock(self) -> list[int]:
        sql = """
            SELECT [AccountID]
            FROM [dbo].[BlogCommentViolationCount]
            WHERE [IsCommentBanned] = 1
              AND [BanExpiresAt] IS NOT NULL
              AND [BanExpiresAt] <= GETUTCDATE()
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        return [int(row[0]) for row in rows]

    async def unlock_comment_privilege(self, account_id: int) -> None:
        sql = """
            UPDATE [dbo].[BlogCommentViolationCount]
            SET [IsCommentBanned] = 0,
                [UnbannedAt] = GETUTCDATE(),
                [UpdatedAt] = GETUTCDATE()
            WHERE [AccountID] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, account_id)

    async def insert_user_notification(
        self,
        *,
        account_id: int,
        title: str,
        message: str,
        idempotency_key: str,
    ) -> None:
        sql = """
            IF NOT EXISTS (
                SELECT 1
                FROM [Notification].[Deliveries]
                WHERE [IdempotencyKey] = ?
            )
            BEGIN
                INSERT INTO [Notification].[Deliveries]
                  ([AccountID], [CampaignID], [TemplateCode], [RecipientType], [Channel],
                   [NotificationType], [Title], [Message], [Payload], [Status], [IdempotencyKey], [CreatedAt])
                VALUES
                  (?, NULL, NULL, 'CUSTOMER', 'WEB_BELL',
                   'SYSTEM', ?, ?, ?, 'Unread', ?, GETUTCDATE())
            END
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, idempotency_key, account_id, title, message, "{}", idempotency_key)
