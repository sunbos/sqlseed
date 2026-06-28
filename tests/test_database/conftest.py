"""Shared pytest fixtures for database adapter tests.

Fixtures previously duplicated across test_sqlalchemy_adapter.py and
test_sqlalchemy_adapter_boundary.py are centralized here. This follows
the standard pytest pattern (fixtures shared by tests in a directory
live in that directory's conftest.py) and eliminates the
redefined-outer-name false positive that pylint reports when a fixture
function shares its name with a test-function parameter.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sa_adapter(tmp_db: str) -> SQLAlchemyAdapter:
    """Create a connected SQLAlchemyAdapter backed by tmp_db."""
    adapter = SQLAlchemyAdapter()
    adapter.connect(tmp_db)
    yield adapter
    adapter.close()


@pytest.fixture
def empty_sa_adapter(tmp_path: Path) -> SQLAlchemyAdapter:
    """Create a SQLAlchemyAdapter connected to an empty database file."""
    db_path = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db_path)
    conn.close()  # Touch the file so SQLite creates it.
    adapter = SQLAlchemyAdapter()
    adapter.connect(db_path)
    yield adapter
    adapter.close()
