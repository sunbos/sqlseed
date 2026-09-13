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
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from collections.abc import Iterator
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


@contextmanager
def sqlite_schema_adapter(path: Path, schema: str) -> Iterator[SQLAlchemyAdapter]:
    """Create a schema and close its adapter even when setup or a test fails."""
    with sqlite_connection(path) as connection:
        connection.executescript(schema)
    adapter = SQLAlchemyAdapter()
    try:
        adapter.connect(str(path))
        yield adapter
    finally:
        adapter.close()


@pytest.fixture(name="counts_database")
def fixture_counts_database(tmp_path: Path) -> Iterator[tuple[Path, SQLAlchemyAdapter]]:
    path = tmp_path / "counts.db"
    with sqlite_schema_adapter(
        path,
        "CREATE TABLE items(value INTEGER NOT NULL UNIQUE CHECK(value>0));"
        "CREATE TABLE audit(value INTEGER);"
        "INSERT INTO items VALUES(9);"
        "CREATE TRIGGER skip_one BEFORE INSERT ON items WHEN NEW.value=1 "
        "BEGIN SELECT RAISE(IGNORE); END;"
        "CREATE TRIGGER log_insert AFTER INSERT ON items BEGIN "
        "INSERT INTO audit VALUES(NEW.value); INSERT INTO audit VALUES(NEW.value); END;",
    ) as adapter:
        yield path, adapter


@pytest.fixture(name="transaction_database")
def fixture_transaction_database(tmp_path: Path) -> Iterator[tuple[Path, SQLAlchemyAdapter]]:
    path = tmp_path / "atomic.db"
    with sqlite_schema_adapter(
        path,
        "CREATE TABLE parents(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE);"
        "CREATE TABLE children(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parents(id));"
        "INSERT INTO parents(id,code) VALUES(40,'old');INSERT INTO children VALUES(1,40);",
    ) as adapter:
        yield path, adapter
