"""Lookup memoization must preserve the database's typed key distinctions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event

from sqlseed.core.expression import ExpressionEngine
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def make_reference(path: Path, column_type: str, keys: list[str]) -> None:
    with sqlite_connection(path) as db:
        db.execute(f"CREATE TABLE reference (lookup_key {column_type} UNIQUE, label TEXT)")
        db.executemany("INSERT INTO reference VALUES (?, ?)", zip(keys, ["first", "second"], strict=True))


@pytest.mark.parametrize("adapter_type", [SQLAlchemyAdapter, RawSQLiteAdapter])
@pytest.mark.parametrize("reverse", [False, True])
def test_equal_python_numbers_keep_distinct_text_lookups(
    tmp_path: Path, adapter_type: type[SQLAlchemyAdapter] | type[RawSQLiteAdapter], reverse: bool
) -> None:
    path = tmp_path / "numbers.sqlite"
    make_reference(path, "TEXT", ["1", "1.0"])
    keys = [1.0, 1] if reverse else [1, 1.0]
    with sqlite_connection(path) as db:
        expected = [db.execute("SELECT label FROM reference WHERE lookup_key=?", (key,)).fetchone()[0] for key in keys]
    with adapter_type() as adapter:
        adapter.connect(str(path))
        engine = ExpressionEngine(db_adapter=adapter)
        actual = [engine._lookup("reference", "label", key, "lookup_key") for key in keys * 2]
    assert expected == (["second", "first"] if reverse else ["first", "second"])
    assert actual == expected * 2


@pytest.mark.parametrize(
    ("stored_keys", "keys"),
    [
        (["true", "1"], [True, 1]),
        (["true", "1"], [1, True]),
        (["1.0", "2.0"], [1.0, 2.0]),
        (["1.0", "2.0"], [2.0, 1.0]),
        (["[1]", "[2]"], [[1], [2]]),
        (['{"a": 1}', '{"a": 2}'], [{"a": 1}, {"a": 2}]),
    ],
)
def test_json_lookup_retains_serialized_key_identity(
    tmp_path: Path, stored_keys: list[str], keys: list[object]
) -> None:
    path = tmp_path / "json.sqlite"
    make_reference(path, "JSON", stored_keys)
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        # Uncached adapter results are checked independently before exercising
        # the expression engine's memoization and repeated evaluation.
        expected = [adapter._lookup_value("reference", "label", key, "lookup_key") for key in keys]
        assert set(expected) == {"first", "second"}
        engine = ExpressionEngine(db_adapter=adapter)
        actual = [
            engine.evaluate("lookup('reference', 'label', value, 'lookup_key')", {"value": key}) for key in keys * 2
        ]
        assert actual == expected * 2


@pytest.mark.parametrize("reverse", [False, True])
def test_equal_instant_datetimes_keep_distinct_text_bindings(tmp_path: Path, reverse: bool) -> None:
    first = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    second = first.astimezone(timezone(timedelta(hours=2)))
    assert first == second
    path = tmp_path / "temporal.sqlite"
    make_reference(path, "TEXT", [first.isoformat(" "), second.isoformat(" ")])
    keys = [second, first] if reverse else [first, second]
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        engine = ExpressionEngine(db_adapter=adapter)
        actual = [engine._lookup("reference", "label", key, "lookup_key") for key in keys * 2]
    assert actual == (["second", "first"] if reverse else ["first", "second"]) * 2


def test_builtin_scalar_results_and_missing_results_remain_cached(tmp_path: Path) -> None:
    path = tmp_path / "cached.sqlite"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE reference (lookup_key TEXT UNIQUE, label TEXT)")
        db.executemany("INSERT INTO reference VALUES (?, ?)", [("known", "found"), ("null", None)])
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        statements: list[str] = []

        def observe(connection, cursor, statement, parameters, context, executemany) -> None:
            if statement.startswith("SELECT ") and "FROM reference" in statement:
                statements.append(statement)

        database_engine = adapter._get_engine()
        event.listen(database_engine, "before_cursor_execute", observe)
        try:
            engine = ExpressionEngine(db_adapter=adapter)
            for _ in range(2):
                for key, expected in [("known", "found"), ("missing", None), ("null", None), (None, None)]:
                    assert engine._lookup("reference", "label", key, "lookup_key") == expected
            assert len(statements) == 4
        finally:
            event.remove(database_engine, "before_cursor_execute", observe)
