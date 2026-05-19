"""
tests/conftest.py
-----------------
Shared pytest fixtures for unit and integration tests.
"""

from __future__ import annotations

import os
import pytest

# ── Patch env before any app imports ─────────────────────────────────────────
os.environ.setdefault("MSSQL_CONNECTION_STRING", "DRIVER={ODBC Driver 17 for SQL Server};SERVER=test;DATABASE=test;UID=sa;PWD=test")
os.environ.setdefault("GROQ_API_KEY", "gsk_test_key")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")


from app.core.config import get_settings  # noqa: E402 — must be after env setup


@pytest.fixture(scope="session")
def settings():
    """Return cached Settings for test session."""
    get_settings.cache_clear()
    return get_settings()
