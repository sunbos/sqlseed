"""Real database regressions for pooled cursors and adapter reconnection."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import OperationalError

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


def test_execute_cursor_keeps_connection_until_closed(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "cursor.db"))
        engine = adapter._get_engine()
        cursor = adapter.execute("SELECT 1 UNION ALL SELECT 2")
        try:
            assert engine.pool.checkedout() == 1
            assert next(cursor) == (1,)
        finally:
            cursor.close()
        assert engine.pool.checkedout() == 0
        cursor.close()


def test_execute_results_survive_pool_disposal(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "cursor.db"))
        cursor = adapter.execute("SELECT 1 UNION ALL SELECT 2")
        try:
            adapter._get_engine().dispose()
            assert cursor.fetchall() == [(1,), (2,)]
        finally:
            cursor.close()


def test_temporary_cursor_remains_open_during_fetch(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "cursor.db"))
        rows = adapter.execute("SELECT 1 UNION ALL SELECT 2").fetchall()
        row = adapter.execute("SELECT 3").fetchone()
        assert rows == [(1,), (2,)]
        assert row == (3,)
        assert adapter._get_engine().pool.checkedout() == 0


def test_cursor_fetchmany_respects_arraysize_and_can_continue_iteration(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "cursor.db"))
        cursor = adapter.execute("SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4")
        try:
            cursor.arraysize = 2
            assert cursor.fetchmany() == [(1,), (2,)]
            assert cursor.fetchmany(1) == [(3,)]
            assert list(cursor) == [(4,)]
            assert cursor.fetchmany() == []
        finally:
            cursor.close()
        cursor.close()
        assert adapter._get_engine().pool.checkedout() == 0
        with pytest.raises(sqlite3.ProgrammingError, match="closed cursor"):
            cursor.fetchone()


def test_temporary_cursor_supports_fetchmany_and_iteration(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "cursor.db"))
        rows = adapter.execute("SELECT 1 UNION ALL SELECT 2").fetchmany(2)
        iterated = list(adapter.execute("SELECT 3 UNION ALL SELECT 4"))
        assert rows == [(1,), (2,)]
        assert iterated == [(3,), (4,)]
        assert adapter._get_engine().pool.checkedout() == 0


def test_reconnect_uses_new_table_schema(tmp_path: Path) -> None:
    first, second = tmp_path / "first.db", tmp_path / "second.db"
    with sqlite3.connect(first) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, old_value TEXT)")
    with sqlite3.connect(second) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, new_value TEXT)")
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(first))
        adapter.batch_insert("items", iter([{"old_value": "old"}]))
        adapter.connect(str(second))
        adapter.batch_insert("items", iter([{"new_value": "new"}]))
        assert adapter.get_sample_rows("items") == [{"id": 1, "new_value": "new"}]


def test_reconnect_is_rejected_inside_transaction(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "first.db"))
        adapter.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)").close()
        with adapter.transaction():
            adapter.batch_insert("items", iter([{"id": 1}]))
            with pytest.raises(RuntimeError, match="transaction"):
                adapter.connect(str(tmp_path / "second.db"))
            assert adapter.get_row_count("items") == 1
        assert adapter.get_row_count("items") == 1


def test_failed_connect_leaves_adapter_disconnected(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        with pytest.raises(OperationalError):
            adapter.connect(str(tmp_path / "missing" / "db.sqlite"))
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.execute("SELECT 1")


def test_key_exists_binds_values_using_column_types(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "typed_keys.db"))
        adapter.execute("CREATE TABLE items (stamp DATETIME, amount DECIMAL(8, 2), UNIQUE(stamp, amount))").close()
        key = {"stamp": datetime(2026, 9, 9, 12, 30), "amount": Decimal("12.50")}
        adapter.batch_insert("items", iter([key]))
        assert adapter._key_exists("items", key)
        assert not adapter._key_exists("items", {**key, "amount": Decimal("13.50")})
        with adapter.transaction():
            pending = {**key, "stamp": datetime(2026, 9, 10, 12, 30)}
            adapter.batch_insert("items", iter([pending]))
            assert adapter._key_exists("items", pending)


@pytest.mark.parametrize("declared_type", ["INT", "INTEGER", "BIGINT", "SMALLINT"])
def test_sqlite_primary_key_metadata_preserves_declared_type(tmp_path: Path, declared_type: str) -> None:
    path = tmp_path / "declared_type.db"
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE items (id {declared_type} NOT NULL PRIMARY KEY, value TEXT)")
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        primary_key = adapter.get_column_info("items")[0]
        assert primary_key.type == declared_type
        assert primary_key.is_primary_key
        assert not primary_key.is_autoincrement


def test_sqlite_declared_types_visible_inside_transaction(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "declared_type_transaction.db"))
        with adapter.transaction():
            adapter.execute(
                'CREATE TABLE "order" (id INT NOT NULL PRIMARY KEY, '
                '"computed" INTEGER GENERATED ALWAYS AS (id + 1) STORED)'
            ).close()
            columns = adapter.get_column_info("order")
            assert columns[0].type == "INT"
            assert columns[1].is_computed
