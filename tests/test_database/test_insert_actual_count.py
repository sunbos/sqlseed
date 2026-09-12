"""Affected-row counts exclude ignored inserts and unrelated trigger effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

    from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter


def test_mixed_ignored_inserts_exclude_trigger_side_effects(counts_database: tuple[Path, SQLAlchemyAdapter]) -> None:
    path, adapter = counts_database
    assert adapter.batch_insert("items", iter({"value": v} for v in (1, 2, 1, 3)), batch_size=2) == 2
    assert adapter.get_row_count("items") == 3
    with sqlite_connection(path) as db:
        assert db.execute("SELECT value FROM audit ORDER BY value").fetchall() == [(2,), (2,), (3,), (3,)]


def test_later_batch_error_rolls_back_actual_inserts_and_trigger_effects(
    counts_database: tuple[Path, SQLAlchemyAdapter],
) -> None:
    _, adapter = counts_database
    rows = iter({"value": v} for v in (1, 2, 3, -1))
    with pytest.raises(IntegrityError):
        adapter.batch_insert("items", rows, batch_size=2)
    assert adapter.get_column_values("items", "value") == [9]
    assert adapter.get_row_count("audit") == 0


def test_actual_counts_share_explicit_transaction(counts_database: tuple[Path, SQLAlchemyAdapter]) -> None:
    path, adapter = counts_database
    with adapter.transaction():
        assert adapter.batch_insert("items", iter([{"value": 1}, {"value": 2}])) == 1
        with sqlite_connection(path) as db:
            assert db.execute("SELECT value FROM items").fetchall() == [(9,)]
    assert adapter.get_row_count("items") == 2
