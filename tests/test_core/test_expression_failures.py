"""Evaluation failures must cross the worker boundary instead of becoming NULL."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.expression import ExpressionEngine
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("expression", ["1 / 0", "random_choice([])", "int(float('inf'))"])
def test_worker_propagates_arithmetic_and_lookup_errors(expression: str) -> None:
    engine = ExpressionEngine()
    with pytest.raises((ZeroDivisionError, IndexError, OverflowError)):
        engine.evaluate(expression, {})


@pytest.mark.parametrize(
    ("adapter_type", "error", "message"),
    [(SQLAlchemyAdapter, RuntimeError, "does not exist"), (RawSQLiteAdapter, sqlite3.ProgrammingError, "same thread")],
)
def test_database_lookup_failure_does_not_become_null(
    tmp_path: Path, adapter_type: type[SQLAlchemyAdapter | RawSQLiteAdapter], error: type[Exception], message: str
) -> None:
    adapter = adapter_type()
    adapter.connect(str(tmp_path / "lookup.db"))
    try:
        engine = ExpressionEngine(db_adapter=adapter)
        with pytest.raises(error, match=message):
            engine.evaluate("lookup('missing', 'value', 1)", {})
    finally:
        adapter.close()
