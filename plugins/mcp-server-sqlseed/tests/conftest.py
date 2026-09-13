"""Shared pytest fixtures for MCP server tests.

Shared fixtures (``pg_url``, ``available_llm_backend``, ``tmp_db``, etc.)
are defined in the rootdir ``conftest.py`` at the repository root and are
auto-discovered by pytest for all test files. No ``pytest_plugins``
declaration is needed here — the rootdir conftest is loaded for every
test file via standard conftest discovery.

This file only defines MCP-server-specific local fixtures.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def tmp_sqlite_db(tmp_path: Path) -> str:
    """Create a temporary SQLite database file for testing."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)")
    conn.commit()
    conn.close()
    return str(db_path)
