"""Boundary tests for the SQLAlchemy adapter."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sa_adapter(tmp_db: str) -> SQLAlchemyAdapter:
    """Create a connected SQLAlchemyAdapter."""
    adapter = SQLAlchemyAdapter()
    adapter.connect(tmp_db)
    yield adapter
    adapter.close()


@pytest.fixture
def empty_sa_adapter(tmp_path: Path) -> SQLAlchemyAdapter:
    """Create a SQLAlchemyAdapter connected to an empty database."""
    db_path = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db_path)
    conn.close()  # Create an empty file
    adapter = SQLAlchemyAdapter()
    adapter.connect(db_path)
    yield adapter
    adapter.close()


class TestSQLAlchemyAdapterBoundary:
    """Tests SQLAlchemyAdapter boundary conditions."""

    def test_get_column_info_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Non-existent table returns []."""
        assert sa_adapter.get_column_info("nonexistent_table") == []

    def test_get_primary_keys_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Non-existent table returns []."""
        assert sa_adapter.get_primary_keys("nonexistent_table") == []

    def test_get_foreign_keys_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Non-existent table returns []."""
        assert sa_adapter.get_foreign_keys("nonexistent_table") == []

    def test_get_index_info_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Non-existent table returns []."""
        assert sa_adapter.get_index_info("nonexistent_table") == []

    def test_get_row_count_nonexistent_table_returns_zero(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Non-existent table returns 0."""
        assert sa_adapter.get_row_count("nonexistent_table") == 0

    def test_get_column_values_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Non-existent table returns []."""
        assert sa_adapter.get_column_values("nonexistent_table", "id") == []

    def test_get_sample_rows_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Non-existent table returns []."""
        assert sa_adapter.get_sample_rows("nonexistent_table") == []

    def test_batch_insert_nonexistent_table_raises_runtime_error(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Non-existent table raises RuntimeError (not NoSuchTableError)."""
        with pytest.raises(RuntimeError):
            sa_adapter.batch_insert("nonexistent_table", iter([{"id": 1}]))

    def test_operation_after_close_raises(self, tmp_db: str) -> None:
        """After close, calling get_table_names raises RuntimeError."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        adapter.close()
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.get_table_names()

    def test_operation_after_context_exit_raises(self, tmp_db: str) -> None:
        """After with-block exit, operations raise RuntimeError."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        with adapter:
            pass
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.get_table_names()

    def test_empty_database_get_table_names_returns_empty(self, empty_sa_adapter: SQLAlchemyAdapter) -> None:
        """Empty database returns []."""
        assert empty_sa_adapter.get_table_names() == []

    def test_connect_to_nonexistent_sqlite_file_creates_it(self, tmp_path: Path) -> None:
        """SQLite auto-creates the file."""
        db_path = str(tmp_path / "new.db")
        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        # Should be operable after connecting
        assert adapter.get_table_names() == []
        adapter.close()

    def test_double_connect_overwrites_engine(self, tmp_db: str) -> None:
        """Repeated connect overwrites engine (no exception, source has no double-connect guard)."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        adapter.connect(tmp_db)  # Should not raise
        assert adapter.get_table_names() == ["orders", "users"]
        adapter.close()

    def test_close_idempotent(self, tmp_db: str) -> None:
        """Multiple close calls do not error."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        adapter.close()
        adapter.close()  # Should not raise

    def test_dialect_accessible_before_connect_raises(self) -> None:
        """Accessing dialect before connect raises RuntimeError."""
        adapter = SQLAlchemyAdapter()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = adapter.dialect


class TestReservedWordsAndSpecialChars:
    """Tests handling of SQL reserved words and special characters."""

    def test_table_name_reserved_word_order(self, tmp_path: Path) -> None:
        """Table name "order" (SQL reserved word) is correctly quoted."""
        db_path = str(tmp_path / "reserved.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE "order" (id INTEGER PRIMARY KEY, name TEXT)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        assert "order" in adapter.get_table_names()
        cols = adapter.get_column_info("order")
        assert len(cols) == 2
        adapter.close()

    def test_table_name_reserved_word_select(self, tmp_path: Path) -> None:
        """Table name "select" is correctly quoted."""
        db_path = str(tmp_path / "reserved.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE "select" (id INTEGER PRIMARY KEY, name TEXT)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        assert "select" in adapter.get_table_names()
        adapter.close()

    def test_column_name_reserved_word(self, tmp_path: Path) -> None:
        """Column names "from" and "where" are correctly quoted."""
        db_path = str(tmp_path / "reserved.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY, "from" TEXT, "where" TEXT)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        cols = adapter.get_column_info("test")
        col_names = [c.name for c in cols]
        assert "from" in col_names
        assert "where" in col_names
        adapter.close()

    def test_table_name_with_special_chars(self, tmp_path: Path) -> None:
        """Table name with double quotes is correctly escaped."""
        db_path = str(tmp_path / "special.db")
        conn = sqlite3.connect(db_path)
        # SQLite table names with special characters need double quotes
        conn.execute('CREATE TABLE "my table" (id INTEGER PRIMARY KEY)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        names = adapter.get_table_names()
        assert "my table" in names
        adapter.close()

    def test_column_name_with_special_chars(self, tmp_path: Path) -> None:
        """Column name with double quotes is correctly escaped."""
        db_path = str(tmp_path / "special.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY, "first name" TEXT)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        cols = adapter.get_column_info("test")
        col_names = [c.name for c in cols]
        assert "first name" in col_names
        adapter.close()

    def test_fill_table_with_reserved_name_e2e(self, tmp_path: Path) -> None:
        """Reserved-word table name full fill flow."""
        db_path = str(tmp_path / "reserved.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE "order" (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')
        conn.commit()
        conn.close()

        import sqlseed  # noqa: PLC0415

        result = sqlseed.fill(db_path, table="order", count=10, provider="base")
        assert result.count == 10

        # Verify data
        conn = sqlite3.connect(db_path)
        cursor = conn.execute('SELECT COUNT(*) FROM "order"')
        assert cursor.fetchone()[0] == 10
        conn.close()
