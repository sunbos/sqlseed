"""Appending respects existing database keys without loading the whole table."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed.core.column_dag import ColumnConstraints, ColumnDAG, ColumnNode
from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.stream import DataStream
from sqlseed.generators.base_provider import BaseProvider
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def _create_full_pair_domain(path: Path) -> None:
    """Populate the only key that the fixed generators can produce."""
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items (a INTEGER NOT NULL, b INTEGER NOT NULL, PRIMARY KEY(a,b))")
        db.execute("INSERT INTO items VALUES (1, 2)")


def _fixed_pair_columns() -> dict[str, dict[str, object]]:
    return {
        "a": {"generator": "choice", "params": {"choices": [1]}},
        "b": {"generator": "choice", "params": {"choices": [2]}},
    }


@pytest.mark.parametrize("constraint", ["PRIMARY KEY", "UNIQUE"])
def test_append_avoids_existing_composite_fk_keys(tmp_path: Path, constraint: str) -> None:
    path = tmp_path / "append.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY);"
            "CREATE TABLE products (id INTEGER PRIMARY KEY);"
            "CREATE TABLE order_items ("
            "order_id INTEGER NOT NULL REFERENCES orders(id),"
            "product_id INTEGER NOT NULL REFERENCES products(id),"
            f"{constraint}(order_id, product_id));"
        )
        db.executemany("INSERT INTO orders VALUES (?)", [(i,) for i in range(1, 21)])
        db.executemany("INSERT INTO products VALUES (?)", [(i,) for i in range(1, 21)])
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        first = orch.fill_table("order_items", count=80, seed=42, batch_size=20, skip_ai=True)
        assert_empty(first.errors, list)
        previous = orch.query("SELECT order_id, product_id FROM order_items")
        second = orch.fill_table("order_items", count=80, seed=42, batch_size=20, skip_ai=True)
        assert_empty(second.errors, list)
        assert second.count == 80
        rows = orch.query("SELECT order_id, product_id FROM order_items")
        pairs = {(row["order_id"], row["product_id"]) for row in rows}
        assert len(rows) == len(pairs) == 160
        assert all((row["order_id"], row["product_id"]) in pairs for row in previous)
        # Components may repeat: only their pair must be unique.
        assert len({row["order_id"] for row in rows}) <= 20
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_append_avoids_existing_single_unique_values(tmp_path: Path) -> None:
    path = tmp_path / "single.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items (code TEXT NOT NULL UNIQUE)")
    columns = {"code": {"generator": "choice", "params": {"choices": [str(i) for i in range(40)]}}}
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        assert_empty(orch.fill_table("items", count=10, columns=columns, seed=42, skip_ai=True).errors, list)
        result = orch.fill_table("items", count=10, columns=columns, seed=42, skip_ai=True)
        assert_empty(result.errors, list)
        assert orch.get_row_count("items") == 20


def test_composite_registration_rolls_back_when_a_later_constraint_fails() -> None:

    specs = {
        name: GeneratorSpec(generator_name="choice", params={"choices": [value]})
        for name, value in (("a", 1), ("b", 2), ("c", 3))
    }
    solver = ConstraintSolver()
    solver.check_and_register_composite("__composite__('b', 'c')", (2, 3))
    stream = DataStream(
        ColumnDAG().build(specs),
        BaseProvider(),
        ExpressionEngine(),
        solver,
        composite_unique_constraints=[["a", "b"], ["b", "c"]],
    )
    assert stream._attempt_row_generation({}, {})[0] is False
    specs["c"].params["choices"] = [4]
    row: dict[str, object] = {}
    assert stream._attempt_row_generation(row, {})[0] is True
    assert row == {"a": 1, "b": 2, "c": 4}
    # A collision must never unregister a tuple belonging to an earlier row.
    assert solver.check_and_register_composite("__composite__('b', 'c')", (2, 3)) is False


def test_composite_registration_rolls_back_when_check_fails() -> None:

    specs = {
        name: GeneratorSpec(generator_name="choice", params={"choices": [value]})
        for name, value in (("a", 1), ("b", 2), ("c", 1))
    }
    stream = DataStream(
        ColumnDAG().build(specs),
        BaseProvider(),
        ExpressionEngine(),
        ConstraintSolver(),
        composite_unique_constraints=[["a", "b"]],
        inequality_constraints=[("a", "c", "<")],
    )
    assert stream._attempt_row_generation({}, {})[0] is False
    specs["c"].params["choices"] = [3]
    row: dict[str, object] = {}
    assert stream._attempt_row_generation(row, {})[0] is True
    assert row == {"a": 1, "b": 2, "c": 3}


@pytest.mark.parametrize("constraint", ["UNIQUE(a)", "UNIQUE(a, b)"])
def test_append_preserves_sql_null_uniqueness(tmp_path: Path, constraint: str) -> None:
    path = tmp_path / "null.db"
    with sqlite_connection(path) as db:
        db.execute(f"CREATE TABLE items (a INTEGER, b INTEGER NOT NULL, {constraint})")
        db.execute("INSERT INTO items VALUES (NULL, 2)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=5,
            columns={
                "a": {"generator": "integer", "null_ratio": 1.0},
                "b": {"generator": "choice", "params": {"choices": [2]}},
            },
            seed=42,
            skip_ai=True,
        )
        assert_empty(result.errors, list)
        assert orch.query("SELECT a, b FROM items") == [{"a": None, "b": 2}] * 6


def test_append_exhausted_composite_domain_preserves_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "full.db"
    _create_full_pair_domain(path)
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=1,
            columns=_fixed_pair_columns(),
            seed=42,
            skip_ai=True,
        )
        assert result.count == 0
        assert len(result.errors) == 1
        assert "after 1000 retries" in result.errors[0]
        assert orch.query("SELECT a, b FROM items") == [{"a": 1, "b": 2}]


def test_clear_before_can_reuse_previous_keys(tmp_path: Path) -> None:
    path = tmp_path / "clear.db"
    _create_full_pair_domain(path)
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=1,
            clear_before=True,
            columns=_fixed_pair_columns(),
            seed=42,
            skip_ai=True,
        )
        assert_empty(result.errors, list)
        assert result.count == 1
        assert orch.query("SELECT a, b FROM items") == [{"a": 1, "b": 2}]


def test_append_database_lookup_uses_column_affinity_and_collation(tmp_path: Path) -> None:
    path = tmp_path / "collation.db"
    with sqlite_connection(path) as db:
        db.execute(
            'CREATE TABLE items ("select" TEXT COLLATE NOCASE NOT NULL, "order" INTEGER NOT NULL, '
            'UNIQUE("select", "order"))'
        )
        db.execute("INSERT INTO items VALUES ('alpha', 1)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=1,
            columns={
                "select": {"generator": "choice", "params": {"choices": ["ALPHA", "BETA"]}},
                "order": {"generator": "choice", "params": {"choices": ["01"]}},
            },
            seed=1,
            skip_ai=True,
        )
        assert_empty(result.errors, list)
        assert orch.query('SELECT "select", "order" FROM items ORDER BY "select"') == [
            {"select": "alpha", "order": 1},
            {"select": "BETA", "order": 1},
        ]


def test_derived_backtrack_releases_other_unique_values_of_discarded_row() -> None:

    nodes = [
        ColumnNode(
            "token",
            GeneratorSpec(generator_name="choice", params={"choices": ["token"]}),
            constraints=ColumnConstraints(is_unique=True),
        ),
        ColumnNode("source", GeneratorSpec(generator_name="choice", params={"choices": [1, 2]})),
        ColumnNode(
            "derived",
            GeneratorSpec(generator_name="__derive__"),
            depends_on=["source"],
            derive_from_sources=["source"],
            expression="value",
            constraints=ColumnConstraints(is_unique=True),
            is_derived=True,
        ),
    ]
    solver = ConstraintSolver()
    solver.check_and_register("derived", 1, is_unique=True)
    stream = DataStream(nodes, BaseProvider(), ExpressionEngine(), solver, seed=1)
    assert next(stream.generate(1)) == [{"token": "token", "source": 2, "derived": 2}]


def test_composite_keys_with_underscored_columns_remain_independent() -> None:

    specs = {
        name: GeneratorSpec(generator_name="choice", params={"choices": [value]})
        for name, value in (("a_b", 1), ("c", 2), ("a", 1), ("b_c", 2))
    }
    stream = DataStream(
        ColumnDAG().build(specs),
        BaseProvider(),
        ExpressionEngine(),
        ConstraintSolver(),
        composite_unique_constraints=[["a_b", "c"], ["a", "b_c"]],
    )
    assert next(stream.generate(1)) == [{"a_b": 1, "c": 2, "a": 1, "b_c": 2}]


@pytest.mark.parametrize("existing", [False, True])
def test_existing_key_checks_remain_bounded_by_consumed_batch(tmp_path: Path, existing: bool) -> None:
    from sqlalchemy import event

    from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

    path = tmp_path / "bounded.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items (a INTEGER NOT NULL UNIQUE)")
        if existing:
            db.execute("INSERT INTO items VALUES (42)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        adapter = orch.database_adapter
        assert isinstance(adapter, SQLAlchemyAdapter)
        probes: list[str] = []

        def record(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            if statement.startswith("SELECT 1"):
                probes.append(statement)

        event.listen(adapter._get_engine(), "before_cursor_execute", record)
        stream = orch._build_stream(
            {"a": GeneratorSpec(generator_name="integer", params={"min_value": 100, "max_value": 1000000})},
            {},
            {"a"},
            None,
            42,
            table_name="items",
        )
        batches = stream.generate(100000, batch_size=3)
        first_batch = next(batches)
        assert len(first_batch) == 3
        assert len(probes) == (4 if existing else 1)
        assert all("LIMIT" in statement for statement in probes)
        assert all("WHERE items.a =" in statement for statement in probes[1:])
        # Previewing a batch must not write it or materialize future batches.
        assert orch.get_row_count("items") == int(existing)
        batches.close()


@pytest.mark.parametrize("column_type", ["DATETIME", "NUMERIC"])
def test_append_key_checks_match_insert_type_bindings(tmp_path: Path, column_type: str) -> None:
    from datetime import datetime
    from decimal import Decimal

    path = tmp_path / "typed.db"
    values = (
        [datetime(2025, 1, 1), datetime(2025, 1, 2)]
        if column_type == "DATETIME"
        else [Decimal("12.50"), Decimal("23.75")]
    )
    with sqlite_connection(path) as db:
        db.execute(f"CREATE TABLE items (value {column_type} NOT NULL UNIQUE)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        orch.database_adapter.batch_insert("items", iter([{"value": values[0]}]))
        result = orch.fill_table(
            "items",
            count=1,
            seed=1,
            columns={"value": {"generator": "choice", "params": {"choices": values}}},
            skip_ai=True,
        )
        assert_empty(result.errors, list)
        assert result.count == 1
        assert orch.query("SELECT COUNT(DISTINCT value) AS n FROM items") == [{"n": 2}]


def test_replayed_seed_prefix_stops_at_finite_retry_budget(tmp_path: Path) -> None:
    path = tmp_path / "replayed.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items (a INTEGER NOT NULL, b INTEGER NOT NULL, PRIMARY KEY(a,b))")
    columns = {name: {"generator": "integer", "params": {"min_value": 1, "max_value": 10000}} for name in ("a", "b")}
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        assert_empty(orch.fill_table("items", count=1001, columns=columns, seed=42, skip_ai=True).errors, list)
        result = orch.fill_table("items", count=1, columns=columns, seed=42, skip_ai=True)
        assert result.count == 0
        assert len(result.errors) == 1
        assert "after 1000 retries" in result.errors[0]
        assert "Reusing a seed may replay existing keys" in result.errors[0]
        assert "does not establish" in result.errors[0]
        assert orch.get_row_count("items") == 1001
