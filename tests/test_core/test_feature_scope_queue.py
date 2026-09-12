"""Resolve FK parent closures with one real metadata read per discovered table."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.features import StructuralFeatureExtractor
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

    from sqlseed.database._protocol import ForeignKeyInfo


@pytest.fixture(name="scope_database")
def create_scope_database(tmp_path: Path) -> Path:
    path = tmp_path / "scope.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE parent(id INTEGER PRIMARY KEY);"
            "CREATE TABLE branch(id INTEGER PRIMARY KEY, p INTEGER REFERENCES parent(id));"
            "CREATE TABLE leaf(id INTEGER PRIMARY KEY, b INTEGER REFERENCES branch(id),"
            " p INTEGER REFERENCES parent(id));"
            "CREATE TABLE cycle_a(id INTEGER PRIMARY KEY, b INTEGER REFERENCES cycle_b(id));"
            "CREATE TABLE cycle_b(id INTEGER PRIMARY KEY, a INTEGER REFERENCES cycle_a(id));"
            "CREATE TABLE self_node(id INTEGER PRIMARY KEY, p INTEGER REFERENCES self_node(id));"
            "CREATE TABLE orphan(id INTEGER PRIMARY KEY, p INTEGER REFERENCES missing(id));"
        )
    return path


@pytest.mark.parametrize("adapter_type", [SQLAlchemyAdapter, RawSQLiteAdapter])
@pytest.mark.parametrize(
    "requested,expected",
    [
        (["leaf"], ["branch", "leaf", "parent"]),
        (["parent", "leaf", "leaf"], ["branch", "leaf", "parent"]),
        (["leaf", "parent"], ["branch", "leaf", "parent"]),
        (["cycle_a"], ["cycle_a", "cycle_b"]),
        (["cycle_b", "cycle_a"], ["cycle_a", "cycle_b"]),
        (["self_node"], ["self_node"]),
        ([], []),
    ],
)
def test_scope_reads_each_reachable_table_once(
    scope_database: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapter_type: type[SQLAlchemyAdapter] | type[RawSQLiteAdapter],
    requested: list[str],
    expected: list[str],
) -> None:
    with adapter_type() as adapter:
        adapter.connect(str(scope_database))
        calls: Counter[str] = Counter()
        read_foreign_keys = adapter.get_foreign_keys

        def tracked_read(table: str) -> list[ForeignKeyInfo]:
            calls[table] += 1
            return read_foreign_keys(table)

        monkeypatch.setattr(adapter, "get_foreign_keys", tracked_read)
        extractor = StructuralFeatureExtractor(adapter)

        assert extractor._resolve_scope(requested) == expected
        assert calls == Counter(dict.fromkeys(expected, 1))


@pytest.mark.parametrize("adapter_type", [SQLAlchemyAdapter, RawSQLiteAdapter])
@pytest.mark.parametrize("requested", [["missing"], ["orphan"]])
def test_scope_retains_adapter_missing_table_behavior(
    scope_database: Path,
    adapter_type: type[SQLAlchemyAdapter] | type[RawSQLiteAdapter],
    requested: list[str],
) -> None:
    with adapter_type() as adapter:
        adapter.connect(str(scope_database))
        resolve_scope = StructuralFeatureExtractor(adapter)._resolve_scope
        assert resolve_scope(requested) == sorted({*requested, "missing"})


@pytest.mark.parametrize("adapter_type", [SQLAlchemyAdapter, RawSQLiteAdapter])
def test_unrestricted_scope_preserves_table_listing(scope_database: Path, adapter_type: type) -> None:
    with adapter_type() as adapter:
        adapter.connect(str(scope_database))
        expected = adapter.get_table_names()
        assert StructuralFeatureExtractor(adapter)._resolve_scope(None) == expected


@pytest.mark.parametrize("error", [RuntimeError("metadata read failed"), KeyboardInterrupt()])
def test_scope_propagates_metadata_reader_failure(
    scope_database: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(scope_database))

        def failed_read(_table: str) -> list[ForeignKeyInfo]:
            raise error

        monkeypatch.setattr(adapter, "get_foreign_keys", failed_read)
        resolve_scope = StructuralFeatureExtractor(adapter)._resolve_scope
        with pytest.raises(type(error)) as caught:
            resolve_scope(["leaf"])
        assert caught.value is error
