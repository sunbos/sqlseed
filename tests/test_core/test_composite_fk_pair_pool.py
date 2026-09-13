"""Composite FK sampling preserves tuples, types, coverage and nullable members."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlseed.core.orchestrator import DataOrchestrator
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def test_typed_pairs_keep_datetime_and_decimal_values(tmp_path: Path) -> None:
    path = tmp_path / "typed_pairs.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE parents(a DATETIME,b NUMERIC(10,2),PRIMARY KEY(a,b));"
            "CREATE TABLE children(a DATETIME NOT NULL,b NUMERIC(10,2) NOT NULL,PRIMARY KEY(a,b),"
            "FOREIGN KEY(a,b) REFERENCES parents(a,b));"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        orch._db.batch_insert(
            "parents",
            iter(
                [
                    {"a": datetime(2026, 1, 1), "b": Decimal("1.25")},
                    {"a": datetime(2026, 1, 1), "b": Decimal("2.50")},
                ]
            ),
        )
        result = orch.fill_table("children", count=2, seed=42, skip_ai=True)
        assert_empty(result.errors, list)
        assert result.count == 2
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)
        assert orch.query("SELECT * FROM children ORDER BY b") == orch.query("SELECT * FROM parents ORDER BY b")


def test_coverage_samples_parent_pairs_across_batches_and_dag_orders_source_first(tmp_path: Path) -> None:
    path = tmp_path / "coverage.db"
    with sqlite_connection(path) as db:
        # Deliberately reverse the child column order relative to the FK order.
        db.executescript(
            "CREATE TABLE parents(a INTEGER,b INTEGER,PRIMARY KEY(a,b));"
            "INSERT INTO parents VALUES(1,10),(1,20),(2,30);"
            "CREATE TABLE children(b INTEGER NOT NULL,a INTEGER NOT NULL,FOREIGN KEY(a,b) REFERENCES parents(a,b));"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "children",
            count=3,
            batch_size=1,
            seed=42,
            skip_ai=True,
            columns={"a": {"generator": "foreign_key", "params": {"strategy": "coverage"}}},
        )
        assert_empty(result.errors, list)
        assert result.count == 3
        assert orch.query("SELECT a,b FROM children ORDER BY b") == [
            {"a": 1, "b": 10},
            {"a": 1, "b": 20},
            {"a": 2, "b": 30},
        ]
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_partial_null_composite_fk_preserves_explicit_null(tmp_path: Path) -> None:
    path = tmp_path / "nullable_pairs.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE parents(a INTEGER,b INTEGER,PRIMARY KEY(a,b));"
            "INSERT INTO parents VALUES(1,10),(1,20);"
            "CREATE TABLE children(a INTEGER,b INTEGER NOT NULL,FOREIGN KEY(a,b) REFERENCES parents(a,b));"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "children", count=10, seed=42, skip_ai=True, columns={"a": {"generator": "foreign_key", "null_ratio": 1.0}}
        )
        assert_empty(result.errors, list)
        assert result.count == 10
        rows = orch.query("SELECT * FROM children")
        assert all(row["a"] is None and row["b"] in {10, 20} for row in rows)
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_parent_null_member_is_filtered_for_nonnullable_child(tmp_path: Path) -> None:
    path = tmp_path / "parent_null.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE parents(a INTEGER,b INTEGER);"
            "CREATE UNIQUE INDEX uq ON parents(a,b DESC);"
            "INSERT INTO parents VALUES(1,10),(1,NULL);"
            "CREATE TABLE children(a INTEGER NOT NULL,b INTEGER NOT NULL,FOREIGN KEY(a,b) REFERENCES parents(a,b));"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("children", count=5, seed=42, skip_ai=True)
        assert_empty(result.errors, list)
        assert result.count == 5
        assert orch.query("SELECT a,b FROM children") == [{"a": 1, "b": 10}] * 5
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_parent_null_member_is_retained_for_nullable_child(tmp_path: Path) -> None:
    path = tmp_path / "allowed_parent_null.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE parents(a INTEGER,b INTEGER,UNIQUE(a,b));"
            "INSERT INTO parents VALUES(1,10),(1,NULL);"
            "CREATE TABLE children(a INTEGER NOT NULL,b INTEGER,FOREIGN KEY(a,b) REFERENCES parents(a,b));"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "children",
            count=2,
            seed=42,
            skip_ai=True,
            columns={
                "a": {"generator": "foreign_key", "params": {"strategy": "coverage"}},
                "b": {"generator": "foreign_key", "null_ratio": 0.0},
            },
        )
        assert_empty(result.errors, list)
        assert result.count == 2
        assert orch.query("SELECT a,b FROM children ORDER BY b") == [{"a": 1, "b": None}, {"a": 1, "b": 10}]
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_all_parent_pairs_rejected_by_child_nullability_fail_before_insert(tmp_path: Path) -> None:
    import pytest

    from sqlseed.generators._protocol import ConfigurationError

    path = tmp_path / "no_usable_pairs.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE parents(a INTEGER,b INTEGER,UNIQUE(a,b));"
            "INSERT INTO parents VALUES(1,NULL);"
            "CREATE TABLE children(a INTEGER NOT NULL,b INTEGER NOT NULL,FOREIGN KEY(a,b) REFERENCES parents(a,b));"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        with pytest.raises(ConfigurationError, match=r"children.*a.*b.*NOT NULL"):
            orch.fill_table("children", count=1, seed=42, skip_ai=True)
        assert orch.get_row_count("children") == 0
        assert orch.query("SELECT * FROM parents") == [{"a": 1, "b": None}]
