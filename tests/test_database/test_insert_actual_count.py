"""Affected-row counts exclude ignored inserts and unrelated trigger effects."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


def database(tmp_path: Path) -> tuple[Path, SQLAlchemyAdapter]:
    path = tmp_path / "counts.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            "CREATE TABLE items(value INTEGER NOT NULL UNIQUE CHECK(value>0));"
            "CREATE TABLE audit(value INTEGER);"
            "INSERT INTO items VALUES(9);"
            "CREATE TRIGGER skip_one BEFORE INSERT ON items WHEN NEW.value=1 "
            "BEGIN SELECT RAISE(IGNORE); END;"
            "CREATE TRIGGER log_insert AFTER INSERT ON items BEGIN "
            "INSERT INTO audit VALUES(NEW.value); INSERT INTO audit VALUES(NEW.value); END;"
        )
    adapter = SQLAlchemyAdapter()
    adapter.connect(str(path))
    return path, adapter


def test_mixed_ignored_inserts_exclude_trigger_side_effects(tmp_path: Path) -> None:
    path, adapter = database(tmp_path)
    try:
        assert adapter.batch_insert("items", iter({"value": v} for v in (1, 2, 1, 3)), batch_size=2) == 2
        assert adapter.get_row_count("items") == 3
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("SELECT value FROM audit ORDER BY value").fetchall() == [(2,), (2,), (3,), (3,)]
    finally:
        adapter.close()


def test_later_batch_error_rolls_back_actual_inserts_and_trigger_effects(tmp_path: Path) -> None:
    _, adapter = database(tmp_path)
    try:
        with pytest.raises(IntegrityError):
            adapter.batch_insert("items", iter({"value": v} for v in (1, 2, 3, -1)), batch_size=2)
        assert adapter.get_column_values("items", "value") == [9]
        assert adapter.get_row_count("audit") == 0
    finally:
        adapter.close()


def test_actual_counts_share_explicit_transaction(tmp_path: Path) -> None:
    path, adapter = database(tmp_path)
    try:
        with adapter.transaction():
            assert adapter.batch_insert("items", iter([{"value": 1}, {"value": 2}])) == 1
            with closing(sqlite3.connect(path)) as db, db:
                assert db.execute("SELECT value FROM items").fetchall() == [(9,)]
        assert adapter.get_row_count("items") == 2
    finally:
        adapter.close()
