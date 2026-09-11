"""Expression lookup keys use the database column's insertion representation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.expression import ExpressionEngine
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("column_type", "key", "missing"),
    [
        ("DATETIME", datetime(2026, 9, 9, 12, 30), datetime(2026, 9, 10, 12, 30)),
        ("DATE", date(2026, 9, 9), date(2026, 9, 10)),
        ("DECIMAL(8, 2)", Decimal("12.50"), Decimal("13.50")),
    ],
)
def test_expression_lookup_finds_typed_keys(tmp_path: Path, column_type: str, key: object, missing: object) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "lookup.db"))
        adapter.execute(f'CREATE TABLE entries (lookup_key {column_type} UNIQUE, "value" TEXT)').close()
        adapter.batch_insert("entries", iter([{"lookup_key": key, "value": "found"}]))
        engine = ExpressionEngine(db_adapter=adapter)
        expression = "lookup('entries', 'value', value, 'lookup_key')"
        assert engine.evaluate(expression, {"value": key}) == "found"
        assert engine.evaluate(expression, {"value": missing}) is None


def test_expression_lookup_sees_uncommitted_typed_keys(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "lookup_transaction.db"))
        adapter.execute("CREATE TABLE entries (stamp DATETIME UNIQUE, value TEXT)").close()
        key = datetime(2026, 9, 9, 12, 30)
        with adapter.transaction():
            adapter.batch_insert("entries", iter([{"stamp": key, "value": "pending"}]))
            engine = ExpressionEngine(db_adapter=adapter)
            assert engine.evaluate("lookup('entries', 'value', value, 'stamp')", {"value": key}) == "pending"


def test_lookup_keeps_adapter_protocol_fallback(tmp_path: Path) -> None:
    with RawSQLiteAdapter() as adapter:
        adapter.connect(str(tmp_path / "raw_lookup.db"))
        adapter.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, value TEXT)").close()
        adapter.batch_insert("entries", iter([{"id": 1, "value": "raw adapter"}]))
        engine = ExpressionEngine(db_adapter=adapter)
        assert engine._lookup("entries", "value", 1) == "raw adapter"
        assert engine._lookup("entries", "value", 2) is None
