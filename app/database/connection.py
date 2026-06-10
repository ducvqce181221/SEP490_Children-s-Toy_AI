"""
app/database/connection.py
--------------------
Async SQL Server connection pool via aioodbc.
Provides an async context manager for obtaining connections.
"""

from __future__ import annotations

import aioodbc
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.configs.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level pool — initialized at startup, closed at shutdown
_pool: aioodbc.Pool | None = None


async def init_db_pool() -> None:
    """Create the aioodbc connection pool. Call once at app startup."""
    global _pool
    settings = get_settings()
    logger.info("Initializing database connection pool...")
    _pool = await aioodbc.create_pool(
        dsn=settings.mssql_connection_string,
        minsize=2,
        maxsize=10,
        autocommit=False,
    )
    logger.info("Database connection pool ready")


async def close_db_pool() -> None:
    """Close the pool. Call once at app shutdown."""
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        logger.info("Database connection pool closed")
        _pool = None


def get_pool() -> aioodbc.Pool:
    """Return the active pool; raises if not initialized."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call init_db_pool() first.")
    return _pool


@asynccontextmanager
async def get_connection() -> AsyncGenerator[aioodbc.Connection, None]:
    """Async context manager that yields a connection from the pool."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_cursor(
    conn: aioodbc.Connection,
) -> AsyncGenerator[aioodbc.Cursor, None]:
    """Async context manager that yields a cursor and auto-commits/rolls back."""
    async with conn.cursor() as cur:
        try:
            yield cur
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
