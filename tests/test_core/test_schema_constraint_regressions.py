"""Literal CHECK intersection and integer-key inference use real SQL semantics."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.check_parser import CheckConstraintParser
from sqlseed.core.orchestrator import DataOrchestrator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("sql_type", ["INT", "BIGINT", "INTEGER"])
def test_sqlite_non_rowid_integer_primary_keys_get_values(tmp_path: Path, sql_type: str) -> None:
    path = tmp_path / "pk.db"
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE items (id {sql_type} NOT NULL PRIMARY KEY)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=5, seed=42, skip_ai=True)
        assert result.errors == []
        assert orch.query("SELECT COUNT(id) AS n, COUNT(DISTINCT id) AS d FROM items") == [{"n": 5, "d": 5}]


@pytest.mark.parametrize("separate", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_conjoined_check_enums_are_intersected(tmp_path: Path, separate: bool, explicit: bool) -> None:
    path = tmp_path / "enum.db"
    checks = "CHECK(x IN (1,2)), CHECK(x IN (2,3))" if separate else "CHECK(x IN (1,2) AND x IN (2,3))"
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE items (x INTEGER NOT NULL, {checks})")
    columns = {"x": {"generator": "choice", "params": {"choices": [1, 2, 3]}}} if explicit else None
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=10, seed=42, columns=columns, skip_ai=True)
        assert result.errors == []
        assert orch.query("SELECT x FROM items") == [{"x": 2}] * 10


@pytest.mark.parametrize("sql_type,generator", [("REAL", "float"), ("INTEGER", "integer")])
@pytest.mark.parametrize("explicit", [False, True])
def test_strict_check_bounds_follow_column_domain(
    tmp_path: Path, sql_type: str, generator: str, explicit: bool
) -> None:
    path = tmp_path / "bounds.db"
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE items (x {sql_type} NOT NULL CHECK(x > 0 AND x < 3))")
    columns = {"x": {"generator": generator}} if explicit else None
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=50, seed=42, columns=columns, skip_ai=True)
        assert result.errors == []
        rows = orch.query("SELECT x FROM items")
        assert all(0 < row["x"] < 3 for row in rows)
        if generator == "float":
            assert any(0 < row["x"] < 1 for row in rows)
        else:
            assert {row["x"] for row in rows} == {1, 2}


def test_parser_preserves_strictness_of_integer_literals() -> None:
    parsed = CheckConstraintParser.parse("x", "x > 0 AND x < 1")
    assert parsed is not None
    assert (parsed.min_value, parsed.max_value) == (0, 1)
    assert parsed.min_exclusive and parsed.max_exclusive


def test_multiple_checks_merge_numeric_and_choice_constraints() -> None:
    parsed = CheckConstraintParser.parse_all("x", ["x IN (1,2,3)", "x > 1", "x < 3"])
    assert parsed is not None
    assert parsed.choices == (2,)


@pytest.mark.parametrize("derived", [False, True])
def test_user_numeric_constraints_are_enforced(tmp_path: Path, derived: bool) -> None:
    from sqlseed.config.models import ColumnConfig

    path = tmp_path / "configured.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (source INTEGER NOT NULL, x INTEGER NOT NULL)")
    x = (
        ColumnConfig(name="x", derive_from="source", expression="value", constraints={"min_value": 10, "max_value": 20})
        if derived
        else ColumnConfig(
            name="x",
            generator="integer",
            params={"min_value": 0, "max_value": 100},
            constraints={"min_value": 10, "max_value": 20},
        )
    )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=5,
            seed=42,
            skip_ai=True,
            column_configs=[
                ColumnConfig(name="source", generator="integer", params={"min_value": 0, "max_value": 100}),
                x,
            ],
        )
        assert result.errors == []
        rows = orch.query("SELECT source, x FROM items")
        assert all(10 <= row["x"] <= 20 for row in rows)
        if derived:
            assert all(row["source"] == row["x"] for row in rows)


def test_user_regex_constraint_is_enforced(tmp_path: Path) -> None:
    from sqlseed.config.models import ColumnConfig

    path = tmp_path / "regex.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (x TEXT NOT NULL)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=5,
            seed=1,
            skip_ai=True,
            column_configs=[
                ColumnConfig(
                    name="x", generator="choice", params={"choices": ["wrong", "OK1"]}, constraints={"regex": "OK[0-9]"}
                )
            ],
        )
        assert result.errors == []
        assert orch.query("SELECT x FROM items") == [{"x": "OK1"}] * 5


def test_mapper_preserves_explicit_invalid_length_bounds() -> None:
    from sqlseed.config.models import ColumnConfig
    from sqlseed.core.mapper import ColumnMapper
    from tests.conftest import make_column_info

    spec = ColumnMapper().map_column(
        make_column_info("sku", "TEXT", nullable=False),
        ColumnConfig(name="sku", generator="string", params={"min_length": 10, "max_length": 5}),
    )
    assert spec.params["min_length"] == 10
    assert spec.params["max_length"] == 5


def test_strict_integer_unique_check_bounds_are_not_widened(tmp_path: Path) -> None:
    path = tmp_path / "strict_unique.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (x INTEGER NOT NULL UNIQUE CHECK(x > 0 AND x < 3))")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        specs, _, _, _ = orch._resolve_specs("items", 2, {"x": {"generator": "integer"}}, None, False)
        assert specs["x"].params == {"min_value": 1, "max_value": 2}
        result = orch.fill_table("items", count=2, seed=42, columns={"x": {"generator": "integer"}}, skip_ai=True)
        assert result.errors == []
        assert sorted(row["x"] for row in orch.query("SELECT x FROM items")) == [1, 2]


def test_nullable_unique_fallback_honors_strict_integer_bounds(tmp_path: Path) -> None:
    path = tmp_path / "nullable_unique.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (x INTEGER UNIQUE CHECK(x > 0 AND x < 3))")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=2, seed=42, skip_ai=True)
        assert result.errors == []
        assert sorted(row["x"] for row in orch.query("SELECT x FROM items")) == [1, 2]


@pytest.mark.parametrize(
    "check", ["rank >= -100 AND rank <= -1", "rank >= 1000000 AND rank <= 1000010", "rank >= 1000000", "rank <= -1"]
)
def test_nullable_unique_fallback_uses_check_domain_outside_default_range(tmp_path: Path, check: str) -> None:
    path = tmp_path / "outside_range.db"
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE items(rank INTEGER UNIQUE CHECK({check}))")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=5, seed=42, skip_ai=True)
        assert result.errors == []
        assert result.count == 5
        assert orch.query("SELECT COUNT(rank) AS n, COUNT(DISTINCT rank) AS d FROM items") == [{"n": 5, "d": 5}]


def test_choice_type_fallback_preserves_numeric_check_range(tmp_path: Path) -> None:
    path = tmp_path / "choice_range.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(rank INTEGER NOT NULL DEFAULT 18 UNIQUE CHECK(rank >= 18 AND rank <= 65))")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=5,
            seed=42,
            skip_ai=True,
            columns={"rank": {"generator": "choice", "params": {"choices": [18]}}},
        )
        assert result.errors == []
        assert result.count == 5
        assert orch.query("SELECT COUNT(rank) AS n, COUNT(DISTINCT rank) AS d FROM items") == [{"n": 5, "d": 5}]


def test_unsatisfiable_user_constraint_fails_without_writes(tmp_path: Path) -> None:
    from sqlseed.config.models import ColumnConfig

    path = tmp_path / "impossible.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (x INTEGER NOT NULL)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=1,
            seed=42,
            skip_ai=True,
            column_configs=[
                ColumnConfig(
                    name="x",
                    generator="choice",
                    params={"choices": [5]},
                    constraints={"min_value": 10, "max_retries": 1},
                )
            ],
        )
        assert result.count == 0
        assert len(result.errors) == 1
        assert "after 1000 retries" in result.errors[0]
        assert orch.get_row_count("items") == 0


def test_invalid_constraint_regex_fails_clearly(tmp_path: Path) -> None:
    from sqlseed.config.models import ColumnConfig

    path = tmp_path / "invalid_regex.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (x TEXT NOT NULL)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=1,
            seed=42,
            skip_ai=True,
            column_configs=[
                ColumnConfig(name="x", generator="choice", params={"choices": ["test"]}, constraints={"regex": "["})
            ],
        )
        assert result.count == 0
        assert len(result.errors) == 1
        assert "invalid constraint regex" in result.errors[0]
        assert orch.get_row_count("items") == 0


def test_separate_or_checks_keep_parentheses_when_intersected() -> None:
    parsed = CheckConstraintParser.parse_all("x", ["x = 1 OR x = 2", "x = 2 OR x = 3"])
    assert parsed is not None
    assert parsed.choices == (2,)


def test_disjoint_check_choices_preserve_empty_non_null_domain() -> None:
    parsed = CheckConstraintParser.parse_all("x", ["x IN (1)", "x IN (2)"])
    assert parsed is not None
    assert parsed.kind == "choice"
    assert parsed.choices == ()
