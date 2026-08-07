# ------------------------------------------------------------------------------
# app/repositories/product_review.py
# ------------------------------------------------------------------------------
# Tầng truy xuất cơ sở dữ liệu (Database Access Layer) cho kiểm duyệt Đánh giá sản phẩm.
# Thực thi các truy vấn T-SQL trực tiếp tới cơ sở dữ liệu SQL Server thông qua aioodbc.
# ------------------------------------------------------------------------------

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


# Repository quản lý các truy vấn CSDL cho đánh giá sản phẩm và hình ảnh kèm theo
class ModerationRepository:

    # Lấy lô (batch) các đánh giá sản phẩm ở trạng thái Pending và chuyển sang Processing
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

    # Nhận giữ (Claim) 1 đánh giá sản phẩm cụ thể theo ReviewID và chuyển sang Processing
    async def fetch_review_by_id(self, review_id: int) -> ReviewRecord | None:
        sql = """
            UPDATE rp
            SET rp.[ModerationStatus] = 'Processing',
                rp.[UpdatedAt] = GETUTCDATE()
            OUTPUT
                INSERTED.[ReviewID], INSERTED.[AccountID], INSERTED.[ProductID],
                INSERTED.[OrderID], INSERTED.[Rating], INSERTED.[Comment],
                INSERTED.[ModerationStatus], INSERTED.[CreatedAt]
            FROM [dbo].[ReviewProducts] rp WITH (ROWLOCK)
            WHERE rp.[ReviewID] = ?
              AND rp.[IsDeleted] = 0
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, review_id)
                row = await cur.fetchone()
        if not row:
            return None
        return ReviewRecord(
            review_id=row[0], account_id=row[1], product_id=row[2],
            order_id=row[3], rating=row[4], comment=row[5],
            moderation_status=ModerationStatus(row[6]), created_at=row[7],
        )

    # Lấy trạng thái kiểm duyệt hiện tại của 1 đánh giá sản phẩm
    async def get_review_status(self, review_id: int) -> str | None:
        sql = "SELECT [ModerationStatus] FROM [dbo].[ReviewProducts] WHERE [ReviewID] = ?"
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, review_id)
                row = await cur.fetchone()
        return row[0] if row else None

    # Lấy danh sách các bản ghi hình ảnh đính kèm theo ReviewID
    async def fetch_images_for_review(self, review_id: int) -> list[ReviewImageRecord]:
        sql = """
            SELECT [ReviewProductImageID], [ReviewProductID], [ImageURL],
                   [ModerationStatus]
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
                image_url=row[2], moderation_status=ModerationStatus(row[3]),
            )
            for row in rows
        ]

    # Đếm số lượng đánh giá bị từ chối gần đây của tài khoản trong vòng N ngày
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

    # Cập nhật trạng thái kiểm duyệt mới cho bản ghi đánh giá sản phẩm (Approved, Rejected, ManualReview)
    async def update_review_status(self, review_id: int, status: ModerationStatus) -> None:
        sql = """
            UPDATE [dbo].[ReviewProducts]
            SET [ModerationStatus] = ?, [UpdatedAt] = GETUTCDATE()
            WHERE [ReviewID] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, status.value, review_id)

    # Cập nhật trạng thái kiểm duyệt cho từng hình ảnh đính kèm
    async def update_image_status(self, image_id: int, status: ModerationStatus) -> None:
        sql = """
            UPDATE [dbo].[ReviewProductImages]
            SET [ModerationStatus] = ?, [UpdatedAt] = GETUTCDATE()
            WHERE [ReviewProductImageID] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, status.value, image_id)

    # Thêm nhật ký kiểm duyệt vào bảng [dbo].[ReviewModerationLogs]
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

    # Đếm số lần gọi LLM bị thất bại liên tiếp của 1 đánh giá
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

    # Lấy danh sách tài khoản Quản trị viên (Admin - Role 2) và Nhân viên (Staff - Role 3) đang hoạt động
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

    # Lấy tên tài khoản của tác giả đánh giá sản phẩm theo ReviewID
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

    # Cập nhật lại nội dung nhận xét sau khi làm sạch teencode/chuẩn hóa văn bản
    async def update_review_comment(self, review_id: int, comment: str) -> None:
        sql = """
            UPDATE [dbo].[ReviewProducts]
            SET [Comment] = ?, [UpdatedAt] = GETUTCDATE()
            WHERE [ReviewID] = ?
        """
        async with get_connection() as conn:
            async with get_cursor(conn) as cur:
                await cur.execute(sql, comment, review_id)

    # Thống kê tổng số lượng đánh giá sản phẩm theo từng trạng thái kiểm duyệt
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


