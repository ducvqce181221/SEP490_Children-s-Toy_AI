# ------------------------------------------------------------------------------
# app/database/connection.py
# ------------------------------------------------------------------------------
# Quản lý Connection Pool kết nối bất đồng bộ tới SQL Server thông qua thư viện aioodbc.
# Cung cấp các async context manager để lấy connection và cursor an toàn.
# ------------------------------------------------------------------------------

from __future__ import annotations

import aioodbc
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.configs.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Khai báo pool kết nối CSDL ở cấp độ module (khởi tạo lúc ứng dụng chạy, đóng lúc shutdown)
_pool: aioodbc.Pool | None = None


# Hàm khởi tạo connection pool aioodbc (Gắn vào sự kiện startup của FastAPI)
async def init_db_pool() -> None:
    # Sử dụng biến toàn cục _pool để lưu trữ instance của connection pool
    global _pool
    settings = get_settings()
    logger.info("Initializing database connection pool...")
    
    # Tạo pool kết nối với minsize=2, maxsize=10, autocommit=False
    _pool = await aioodbc.create_pool(
        dsn=settings.mssql_connection_string,
        minsize=2,
        maxsize=10,
        autocommit=False,
    )
    logger.info("Database connection pool ready")


# Hàm đóng connection pool aioodbc (Gắn vào sự kiện shutdown của FastAPI)
async def close_db_pool() -> None:
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        logger.info("Database connection pool closed")
        _pool = None


# Hàm lấy instance connection pool đang hoạt động (Báo lỗi nếu chưa được khởi tạo)
def get_pool() -> aioodbc.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call init_db_pool() first.")
    return _pool


# Context manager bất đồng bộ để mượn 1 kết nối (connection) từ pool
@asynccontextmanager
async def get_connection() -> AsyncGenerator[aioodbc.Connection, None]:
    pool = get_pool()
    # Tự động trả kết nối về pool sau khi dùng xong
    async with pool.acquire() as conn:
        yield conn


# Context manager bất đồng bộ để tạo con trỏ (cursor) và tự động Commit / Rollback giao dịch
@asynccontextmanager
async def get_cursor(
    conn: aioodbc.Connection,
) -> AsyncGenerator[aioodbc.Cursor, None]:
    async with conn.cursor() as cur:
        try:
            yield cur
            # Tự động commit nếu không gặp lỗi
            await conn.commit()
        except Exception:
            # Tự động rollback nếu xảy ra ngoại lệ
            await conn.rollback()
            raise

