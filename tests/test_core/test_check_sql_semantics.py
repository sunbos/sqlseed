"""CHECK adaptation preserves representable decimals and SQL equality semantics."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.check_parser import CheckConstraintParser
from sqlseed.core.orchestrator import DataOrchestrator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("lower,upper,expected", [(0.005, 0.015, 0.01), (-0.015, -0.005, -0.01)])
@pytest.mark.parametrize("explicit", [False, True])
def test_float_check_keeps_valid_precision_grid_point(
    tmp_path: Path, lower: float, upper: float, expected: float, explicit: bool
) -> None:
    path = tmp_path / "grid.db"
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE items (sample REAL NOT NULL CHECK(sample > {lower} AND sample < {upper}))")
        db.execute("INSERT INTO items VALUES (?)", (expected,))
    columns = {"sample": {"generator": "float", "params": {"precision": 2}}} if explicit else None
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=5, columns=columns, seed=42, skip_ai=True)
        assert result.errors == []
        assert orch.query("SELECT sample FROM items") == [{"sample": expected}] * 6


@pytest.mark.parametrize(
    "sql_type,first,second,existing",
    [("INTEGER", "'1','2'", "1,2", 1), ("TEXT COLLATE NOCASE", "'a'", "'A'", "a")],
)
def test_check_intersection_does_not_claim_sql_equivalent_literals_are_disjoint(
    tmp_path: Path, sql_type: str, first: str, second: str, existing: object
) -> None:
    path = tmp_path / "equality.db"
    with sqlite3.connect(path) as db:
        db.execute(
            f"CREATE TABLE items (value {sql_type} NOT NULL CHECK(value IN ({first})) CHECK(value IN ({second})))"
        )
        db.execute("INSERT INTO items VALUES (?)", (existing,))
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=5, seed=42, skip_ai=True)
        assert result.errors == []
        assert orch.get_row_count("items") == 6


def test_ambiguous_enum_candidates_still_obey_database_rejection(tmp_path: Path) -> None:
    path = tmp_path / "binary.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE items (value TEXT COLLATE BINARY NOT NULL CHECK(value IN ('a')) CHECK(value IN ('A')))"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=1, seed=42, skip_ai=True)
        assert result.count == 0
        assert len(result.errors) == 1
        assert "CHECK constraint failed" in result.errors[0]
        assert orch.get_row_count("items") == 0


@pytest.mark.parametrize("explicit", [False, True])
def test_check_constraints_keep_distinct_non_ascii_column_names(tmp_path: Path, explicit: bool) -> None:
    path = tmp_path / "identifiers.db"
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE items ("Ä" INTEGER NOT NULL CHECK("Ä" = 1), "ä" INTEGER NOT NULL CHECK("ä" = 2))')
        db.execute("INSERT INTO items VALUES (1, 2)")
        assert db.execute('SELECT "Ä", "ä" FROM items').fetchall() == [(1, 2)]
    columns = (
        {name: {"generator": "choice", "params": {"choices": [1, 2]}} for name in ("Ä", "ä")} if explicit else None
    )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=3, columns=columns, seed=42, skip_ai=True)
        assert result.errors == []
        assert result.count == 3
        assert orch.query('SELECT "Ä", "ä" FROM items') == [{"Ä": 1, "ä": 2}] * 4


def test_cross_column_check_keeps_distinct_non_ascii_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "cross_identifiers.db"
    expression = '"Ä" < "ä"'
    with sqlite3.connect(path) as db:
        db.execute(f'CREATE TABLE items ("Ä" INTEGER, "ä" INTEGER, CHECK({expression}))')
        db.execute("INSERT INTO items VALUES (1, 2)")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            db.execute("INSERT INTO items VALUES (2, 1)")
    assert CheckConstraintParser.is_cross_column(expression, ["Ä", "ä"])


def test_exact_length_fallback_keeps_distinct_non_ascii_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "length_identifiers.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (Ä TEXT NOT NULL CHECK(LENGTH(Ä)=1), ä TEXT NOT NULL CHECK(LENGTH(ä)=2))")
        db.execute("INSERT INTO items VALUES ('a', 'bb')")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=3, seed=42, skip_ai=True)
        assert result.errors == []
        assert result.count == 3
        assert (
            orch.query("SELECT LENGTH(Ä) AS first, LENGTH(ä) AS second FROM items") == [{"first": 1, "second": 2}] * 4
        )
