"""Tests for ``sqlseed.database._sqlite_schema.detect_sqlite_autoincrement``.

Covers the parenthesis-aware SQL definition splitter and the AUTOINCREMENT
detection logic across a variety of CREATE TABLE DDL variants.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from sqlseed.database._sqlite_schema import (
    _split_sql_definitions,
    detect_sqlite_autoincrement,
)


class _FakeCursor:
    """Minimal cursor-like object returning a single row from fetchone()."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


def _make_execute_fn(ddl: str | None) -> MagicMock:
    """Return a mock execute_fn that yields a CREATE TABLE DDL row."""
    row: tuple[Any, ...] = (ddl,) if ddl is not None else (None,)
    cursor = _FakeCursor(row)
    return MagicMock(return_value=cursor)


# ---------------------------------------------------------------------------
# _split_sql_definitions unit tests
# ---------------------------------------------------------------------------


class TestSplitSqlDefinitions:
    def test_basic_two_columns(self) -> None:
        sql = "CREATE TABLE t (a INTEGER, b TEXT)"
        assert _split_sql_definitions(sql) == ["a INTEGER", "b TEXT"]

    def test_decimal_with_comma(self) -> None:
        sql = "CREATE TABLE t (price DECIMAL(10,2), name TEXT)"
        assert _split_sql_definitions(sql) == ["price DECIMAL(10,2)", "name TEXT"]

    def test_check_constraint_with_comma(self) -> None:
        sql = "CREATE TABLE t (status INTEGER CHECK(status IN (1,2,3)), name TEXT)"
        assert _split_sql_definitions(sql) == [
            "status INTEGER CHECK(status IN (1,2,3))",
            "name TEXT",
        ]

    def test_nested_subquery_in_check(self) -> None:
        sql = "CREATE TABLE t (x CHECK(x IN (SELECT y FROM (SELECT * FROM t2))), z TEXT)"
        parts = _split_sql_definitions(sql)
        assert len(parts) == 2
        assert parts[0].startswith("x CHECK")
        assert parts[1] == "z TEXT"

    def test_foreign_key_clause(self) -> None:
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY, other_id INTEGER FOREIGN KEY(other_id) REFERENCES other(id))"
        parts = _split_sql_definitions(sql)
        assert len(parts) == 2

    def test_empty_parens(self) -> None:
        sql = "CREATE TABLE t ()"
        assert _split_sql_definitions(sql) == []

    def test_no_parens(self) -> None:
        sql = "CREATE TABLE t"
        assert _split_sql_definitions(sql) == []

    def test_strips_whitespace(self) -> None:
        sql = "CREATE TABLE t (  a INTEGER  ,  b TEXT  )"
        assert _split_sql_definitions(sql) == ["a INTEGER", "b TEXT"]


# ---------------------------------------------------------------------------
# detect_sqlite_autoincrement tests
# ---------------------------------------------------------------------------


class TestDetectSqliteAutoincrement:
    def test_basic_autoincrement(self) -> None:
        ddl = "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "users", "id") is True

    def test_decimal_column_with_autoincrement(self) -> None:
        ddl = "CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, price DECIMAL(10,2))"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "products", "id") is True

    def test_check_constraint_with_autoincrement(self) -> None:
        ddl = "CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, status INTEGER CHECK(status IN (1,2,3)))"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "orders", "id") is True

    def test_lowercase_autoincrement(self) -> None:
        ddl = "CREATE TABLE t (id integer primary key autoincrement)"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "id") is True

    def test_mixed_case_autoincrement(self) -> None:
        ddl = "CREATE TABLE t (id Integer Primary Key Autoincrement)"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "id") is True

    def test_multiline_ddl(self) -> None:
        ddl = "CREATE TABLE t (\n  id INTEGER PRIMARY KEY AUTOINCREMENT,\n  name TEXT\n)"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "id") is True

    def test_nested_subquery_with_autoincrement(self) -> None:
        ddl = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, x CHECK(x IN (SELECT y FROM (SELECT * FROM t2))))"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "id") is True

    def test_no_autoincrement_returns_false(self) -> None:
        ddl = "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "id") is False

    def test_autoincrement_on_other_column_returns_false_for_target(self) -> None:
        """Regression: previously, presence of AUTOINCREMENT anywhere caused
        all INTEGER PRIMARY KEY columns to be reported as autoincrement."""
        ddl = "CREATE TABLE t (a INTEGER PRIMARY KEY, b INTEGER PRIMARY KEY AUTOINCREMENT)"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "a") is False
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "b") is True

    def test_non_integer_primary_key_returns_false(self) -> None:
        ddl = "CREATE TABLE t (id TEXT PRIMARY KEY AUTOINCREMENT, name TEXT)"
        # AUTOINCREMENT on non-INTEGER is invalid SQLite, but the detector
        # should still return False because "INTEGER" is required.
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "id") is False

    def test_column_name_not_present(self) -> None:
        ddl = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "name") is False

    def test_no_ddl_returns_false(self) -> None:
        assert detect_sqlite_autoincrement(_make_execute_fn(None), "t", "id") is False

    def test_execute_fn_raises_returns_false(self) -> None:
        mock = MagicMock(side_effect=sqlite3.Error("connection closed"))
        assert detect_sqlite_autoincrement(mock, "t", "id") is False

    def test_column_name_word_boundary(self) -> None:
        """Column 'auto' should not match inside 'AUTOINCREMENT' keyword."""
        ddl = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, auto TEXT)"
        assert detect_sqlite_autoincrement(_make_execute_fn(ddl), "t", "auto") is False


# ---------------------------------------------------------------------------
# Integration: real in-memory SQLite
# ---------------------------------------------------------------------------


class TestDetectSqliteAutoincrementIntegration:
    """Verify against a real sqlite3 connection to catch parser drift."""

    @pytest.fixture
    def conn(self) -> sqlite3.Connection:
        return sqlite3.connect(":memory:")

    def test_real_autoincrement(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        assert detect_sqlite_autoincrement(conn.execute, "t", "id") is True

    def test_real_no_autoincrement(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        assert detect_sqlite_autoincrement(conn.execute, "t", "id") is False

    def test_real_decimal_with_autoincrement(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, price DECIMAL(10,2))")
        assert detect_sqlite_autoincrement(conn.execute, "t", "id") is True
