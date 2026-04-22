from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed.database.sqlite_utils_adapter import SQLiteUtilsAdapter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture
def _sqlite_test_db(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name TEXT NOT NULL, email TEXT, age INTEGER, active INTEGER DEFAULT 1)"
    )
    conn.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "user_id INTEGER REFERENCES users(id), amount REAL, created_at TEXT)"
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def _adapter(_sqlite_test_db: str) -> Generator[SQLiteUtilsAdapter, None, None]:
    a = SQLiteUtilsAdapter()
    a.connect(_sqlite_test_db)
    yield a
    a.close()


@pytest.fixture
def _sample_users_data() -> list[dict[str, Any]]:
    return [
        {"name": "Alice", "email": "alice@test.com", "age": 30, "active": 1},
        {"name": "Bob", "email": "bob@test.com", "age": 25, "active": 1},
    ]


class TestSQLiteUtilsAdapter:
    def test_connect_and_close(self, _sqlite_test_db: str) -> None:
        a = SQLiteUtilsAdapter()
        a.connect(_sqlite_test_db)
        assert a._db is not None
        a.close()
        assert a._db is None

    def test_get_table_names(self, _adapter: SQLiteUtilsAdapter) -> None:
        tables = _adapter.get_table_names()
        assert "users" in tables
        assert "orders" in tables

    def test_get_column_info(self, _adapter: SQLiteUtilsAdapter) -> None:
        columns = _adapter.get_column_info("users")
        col_names = [c.name for c in columns]
        assert "id" in col_names
        assert "name" in col_names
        assert "email" in col_names
        assert "age" in col_names
        assert "active" in col_names

        id_col = next(c for c in columns if c.name == "id")
        assert id_col.is_primary_key is True
        assert id_col.is_autoincrement is True

        name_col = next(c for c in columns if c.name == "name")
        assert name_col.type is not None

    def test_get_primary_keys(self, _adapter: SQLiteUtilsAdapter) -> None:
        pks = _adapter.get_primary_keys("users")
        assert "id" in pks

    def test_get_foreign_keys(self, _adapter: SQLiteUtilsAdapter) -> None:
        fks = _adapter.get_foreign_keys("orders")
        assert len(fks) >= 1
        fk = fks[0]
        assert fk.column == "user_id"
        assert fk.ref_table == "users"
        assert fk.ref_column == "id"

    def test_batch_insert(self, _adapter: SQLiteUtilsAdapter, _sample_users_data: list[dict[str, Any]]) -> None:
        inserted = _adapter.batch_insert("users", iter(_sample_users_data), batch_size=100)
        assert inserted == 2
        count = _adapter.get_row_count("users")
        assert count == 2

    def test_batch_insert_large(self, _adapter: SQLiteUtilsAdapter) -> None:
        data = [{"name": f"User{i}", "email": f"user{i}@test.com", "age": 20 + i % 50, "active": 1} for i in range(100)]
        inserted = _adapter.batch_insert("users", iter(data), batch_size=30)
        assert inserted == 100

    def test_clear_table(self, _adapter: SQLiteUtilsAdapter) -> None:
        data = [{"name": "Alice", "email": "a@t.com", "age": 30, "active": 1}]
        _adapter.batch_insert("users", iter(data))
        assert _adapter.get_row_count("users") == 1
        _adapter.clear_table("users")
        assert _adapter.get_row_count("users") == 0

    def test_get_column_values(self, _adapter: SQLiteUtilsAdapter, _sample_users_data: list[dict[str, Any]]) -> None:
        _adapter.batch_insert("users", iter(_sample_users_data))
        names = _adapter.get_column_values("users", "name")
        assert "Alice" in names
        assert "Bob" in names

    def test_context_manager(self, _sqlite_test_db: str) -> None:
        with SQLiteUtilsAdapter() as a:
            a.connect(_sqlite_test_db)
            tables = a.get_table_names()
            assert len(tables) >= 1

    def test_optimize_and_restore(self, _adapter: SQLiteUtilsAdapter) -> None:
        _adapter.optimize_for_bulk_write(50000)
        _adapter.restore_settings()

    def test_get_row_count(self, _adapter: SQLiteUtilsAdapter) -> None:
        assert _adapter.get_row_count("users") == 0
        data = [{"name": "A", "email": "a@t.com", "age": 20, "active": 1}]
        _adapter.batch_insert("users", iter(data))
        assert _adapter.get_row_count("users") == 1
