"""Contract tests for database adapter implementations."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path

    from sqlseed.database._protocol import DatabaseAdapter


def _create_test_db(db_path: str) -> None:
    """Create a test database (users + orders tables)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """
    )
    conn.execute("CREATE INDEX idx_orders_user ON orders(user_id)")
    conn.commit()
    conn.close()


class DatabaseAdapterContract:
    """Base class for DatabaseAdapter protocol contract tests.

    Subclasses must implement create_adapter() and db_path fixture.
    """

    def create_adapter(self, db_path: str) -> DatabaseAdapter:  # pragma: no cover
        raise NotImplementedError

    def get_db_path(self, tmp_path: Path) -> str:  # pragma: no cover
        raise NotImplementedError

    @pytest.fixture
    def adapter_and_path(self, tmp_path: Path) -> Any:
        db_path = self.get_db_path(tmp_path)
        _create_test_db(db_path)
        adapter = self.create_adapter(db_path)
        adapter.connect(db_path)
        yield adapter, db_path
        adapter.close()

    def test_get_table_names(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        names = adapter.get_table_names()
        assert "users" in names
        assert "orders" in names

    def test_get_column_info_structure(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        cols = adapter.get_column_info("users")
        assert len(cols) >= 2
        col_names = [c.name for c in cols]
        assert "id" in col_names
        assert "name" in col_names

    def test_get_primary_keys_correct(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        pks = adapter.get_primary_keys("users")
        assert pks == ["id"]

    def test_get_foreign_keys_correct(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        fks = adapter.get_foreign_keys("orders")
        assert len(fks) == 1
        assert fks[0].column == "user_id"
        assert fks[0].ref_table == "users"

    def test_batch_insert_and_count(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(10)]
        count = adapter.batch_insert("users", iter(data))
        assert count == 10
        assert adapter.get_row_count("users") == 10

    def test_batch_insert_large(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(1000)]
        count = adapter.batch_insert("users", iter(data))
        assert count == 1000
        assert adapter.get_row_count("users") == 1000

    def test_clear_table_resets_count(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(5)]
        adapter.batch_insert("users", iter(data))
        assert adapter.get_row_count("users") == 5
        adapter.clear_table("users")
        assert adapter.get_row_count("users") == 0

    def test_clear_table_resets_autoincrement(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(5)]
        adapter.batch_insert("users", iter(data))
        adapter.clear_table("users")
        # Insert new data, id should start from 1
        adapter.batch_insert("users", iter([{"name": "new", "email": "new@test.com"}]))
        rows = adapter.get_sample_rows("users", limit=1)
        assert rows[0]["id"] == 1

    def test_get_row_count_empty_table(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        assert adapter.get_row_count("users") == 0

    def test_get_sample_rows_structure(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(3)]
        adapter.batch_insert("users", iter(data))
        rows = adapter.get_sample_rows("users", limit=2)
        assert isinstance(rows, list)
        assert len(rows) == 2
        assert all(isinstance(r, dict) for r in rows)

    def test_get_column_values_correct(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": "alice", "email": "a@test.com"}, {"name": "bob", "email": "b@test.com"}]
        adapter.batch_insert("users", iter(data))
        names = adapter.get_column_values("users", "name")
        assert "alice" in names
        assert "bob" in names

    def test_get_index_info_correct(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        indexes = adapter.get_index_info("orders")
        # orders table has the idx_orders_user index
        index_names = [idx.name for idx in indexes]
        assert "idx_orders_user" in index_names

    def test_execute_select(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": "test", "email": "t@test.com"}]
        adapter.batch_insert("users", iter(data))
        cursor = adapter.execute("SELECT COUNT(*) FROM users")
        # cursor should support fetchone
        row = cursor.fetchone() if hasattr(cursor, "fetchone") else cursor
        assert row is not None

    def test_nonexistent_table_returns_empty(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        assert adapter.get_column_info("nonexistent") == []
        assert adapter.get_primary_keys("nonexistent") == []
        assert adapter.get_foreign_keys("nonexistent") == []
        assert adapter.get_row_count("nonexistent") == 0


class TestRawSQLiteContract(DatabaseAdapterContract):
    """Contract tests for RawSQLiteAdapter."""

    def create_adapter(self, db_path: str) -> DatabaseAdapter:
        return RawSQLiteAdapter()

    def get_db_path(self, tmp_path: Path) -> str:
        return str(tmp_path / "raw_test.db")

    def test_nonexistent_table_returns_empty(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        assert adapter.get_column_info("nonexistent") == []
        assert adapter.get_primary_keys("nonexistent") == []
        assert adapter.get_foreign_keys("nonexistent") == []
        # RawSQLiteAdapter.get_row_count raises sqlite3.OperationalError for non-existent tables
        with pytest.raises(sqlite3.OperationalError):
            adapter.get_row_count("nonexistent")


class TestSQLAlchemyContract(DatabaseAdapterContract):
    """Contract tests for SQLAlchemyAdapter."""

    def create_adapter(self, db_path: str) -> DatabaseAdapter:
        return SQLAlchemyAdapter()

    def get_db_path(self, tmp_path: Path) -> str:
        return str(tmp_path / "sa_test.db")


class TestAdapterConsistency:
    """Tests behavior consistency between SQLAlchemyAdapter and RawSQLiteAdapter."""

    @pytest.fixture
    def dual_adapters(self, tmp_path: Path) -> Any:
        """Create two adapters connected to the same database."""
        db_path = str(tmp_path / "consistency.db")
        _create_test_db(db_path)

        # Insert some test data
        conn = sqlite3.connect(db_path)
        for i in range(10):
            conn.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)",
                [f"user_{i}", f"u{i}@test.com"],
            )
        conn.commit()
        conn.close()

        raw = RawSQLiteAdapter()
        raw.connect(db_path)
        sa = SQLAlchemyAdapter()
        sa.connect(db_path)
        yield raw, sa, db_path
        raw.close()
        sa.close()

    def test_both_adapters_same_column_info(self, dual_adapters: Any) -> None:
        """Same DB, both adapters return the same ColumnInfo."""
        raw, sa, _ = dual_adapters
        raw_cols = raw.get_column_info("users")
        sa_cols = sa.get_column_info("users")

        assert len(raw_cols) == len(sa_cols)
        for r, s in zip(raw_cols, sa_cols, strict=True):
            assert r.name == s.name
            assert r.type == s.type
            assert r.nullable == s.nullable
            assert r.is_primary_key == s.is_primary_key

    def test_both_adapters_same_row_count(self, dual_adapters: Any) -> None:
        """Same DB, both adapters return the same row count."""
        raw, sa, _ = dual_adapters
        assert raw.get_row_count("users") == sa.get_row_count("users")
        assert raw.get_row_count("users") == 10

    def test_both_adapters_same_foreign_keys(self, dual_adapters: Any) -> None:
        """Same DB, both adapters return the same FKs."""
        raw, sa, _ = dual_adapters
        raw_fks = raw.get_foreign_keys("orders")
        sa_fks = sa.get_foreign_keys("orders")

        assert len(raw_fks) == len(sa_fks)
        for r, s in zip(raw_fks, sa_fks, strict=True):
            assert r.column == s.column
            assert r.ref_table == s.ref_table
            assert r.ref_column == s.ref_column

    def test_both_adapters_same_sample_rows(self, dual_adapters: Any) -> None:
        """Same DB, both adapters return the same sample rows."""
        raw, sa, _ = dual_adapters
        raw_rows = raw.get_sample_rows("users", limit=5)
        sa_rows = sa.get_sample_rows("users", limit=5)

        assert len(raw_rows) == len(sa_rows)
        # Verify id fields match (order may differ, but the set of values should be the same)
        raw_ids = {r["id"] for r in raw_rows}
        sa_ids = {r["id"] for r in sa_rows}
        assert raw_ids == sa_ids
