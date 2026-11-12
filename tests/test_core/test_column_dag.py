from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed import connect
from sqlseed.config.models import ColumnConfig, ColumnConstraintsConfig
from sqlseed.core.column_dag import ColumnDAG, ColumnNode
from sqlseed.core.mapper import GeneratorSpec
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


class TestColumnNode:
    def test_is_skip_true(self) -> None:
        spec = GeneratorSpec(generator_name="skip")
        node = ColumnNode(name="id", generator_spec=spec)
        assert node.is_skip is True

    def test_is_skip_false(self) -> None:
        spec = GeneratorSpec(generator_name="string")
        node = ColumnNode(name="name", generator_spec=spec)
        assert node.is_skip is False


class TestColumnDAG:
    def test_build_simple_columns(self) -> None:
        specs = {
            "id": GeneratorSpec(generator_name="skip"),
            "name": GeneratorSpec(generator_name="string"),
            "email": GeneratorSpec(generator_name="email"),
        }
        dag = ColumnDAG()
        nodes = dag.build(specs)
        names = [n.name for n in nodes]
        assert set(names) == {"id", "name", "email"}

    def test_build_with_derived_column(self) -> None:
        specs = {
            "project_no": GeneratorSpec(generator_name="string"),
            "short_code": GeneratorSpec(generator_name="__derive__"),
        }
        configs = [
            ColumnConfig(name="project_no", generator="string"),
            ColumnConfig(name="short_code", derive_from="project_no", expression="value[-8:]"),
        ]
        dag = ColumnDAG()
        nodes = dag.build(specs, configs)
        names = [n.name for n in nodes]
        assert names.index("project_no") < names.index("short_code")
        short_code_node = next(n for n in nodes if n.name == "short_code")
        assert short_code_node.is_derived is True
        assert short_code_node.depends_on == ["project_no"]
        assert short_code_node.expression == "value[-8:]"

    def test_build_with_unique_constraint(self) -> None:
        specs = {
            "email": GeneratorSpec(generator_name="email"),
            "name": GeneratorSpec(generator_name="string"),
        }
        dag = ColumnDAG()
        nodes = dag.build(specs, unique_columns={"email"})
        email_node = next(n for n in nodes if n.name == "email")
        assert email_node.constraints is not None
        assert email_node.constraints.is_unique is True

    def test_build_with_column_config_constraints(self) -> None:
        specs = {
            "age": GeneratorSpec(generator_name="integer"),
        }
        configs = [
            ColumnConfig(
                name="age",
                generator="integer",
                constraints=ColumnConstraintsConfig(unique=True, max_retries=50),
            ),
        ]
        dag = ColumnDAG()
        nodes = dag.build(specs, configs)
        age_node = next(n for n in nodes if n.name == "age")
        assert age_node.constraints is not None
        assert age_node.constraints.is_unique is True
        assert age_node.constraints.max_retries == 50

    def test_topological_sort_order(self) -> None:
        specs = {
            "a": GeneratorSpec(generator_name="string"),
            "b": GeneratorSpec(generator_name="__derive__"),
            "c": GeneratorSpec(generator_name="__derive__"),
        }
        configs = [
            ColumnConfig(name="a", generator="string"),
            ColumnConfig(name="b", derive_from="a", expression="upper(value)"),
            ColumnConfig(name="c", derive_from="b", expression="lower(value)"),
        ]
        dag = ColumnDAG()
        nodes = dag.build(specs, configs)
        names = [n.name for n in nodes]
        assert names.index("a") < names.index("b")
        assert names.index("b") < names.index("c")

    def test_circular_dependency_raises(self) -> None:
        specs = {
            "a": GeneratorSpec(generator_name="__derive__"),
            "b": GeneratorSpec(generator_name="__derive__"),
        }
        configs = [
            ColumnConfig(name="a", derive_from="b", expression="value"),
            ColumnConfig(name="b", derive_from="a", expression="value"),
        ]
        dag = ColumnDAG()
        with pytest.raises(ValueError, match="Circular dependency"):
            dag.build(specs, configs)


@pytest.mark.parametrize(
    ("expression", "references"),
    [
        ('value + row["later"]', ["later"]),
        ('value + row ["later"]', ["later"]),
        ('value + row\t["later"]', ["later"]),
        ('value + (row)["later"]', ["later"]),
        ('(value + row\n["later"])', ["later"]),
        ('  value + row ["later"]  ', ["later"]),
        ('value + row["cost\'s value"]', ["cost's value"]),
        ("value + row['cost\\'s value']", ["cost's value"]),
        ('value + row["later" " column"]', ["later column"]),
        ("value + len(\"row['result']\")", []),
        ("value + 1 # row['result']", []),
        ("value + borrowed_row['later']", []),
        ("value + context.row['later']", []),
        ("value + row[value]", []),
        ("value + row[0]", []),
        ("value + row['later'] + row['later'] + row['source']", ["later"]),
        ("value + row['later'", []),
        ('value + row ["later"]; row["result"]', ["later"]),
        ('value + row ["later"]\nrow["result"]', ["later"]),
        ('value; row["result"]', []),
        ('# row["result"]', []),
    ],
)
def test_literal_row_dependencies_follow_expression_syntax(expression: str, references: list[str]) -> None:
    specs = {
        "source": GeneratorSpec(generator_name="integer"),
        "result": GeneratorSpec(generator_name="__derive__"),
        **{name: GeneratorSpec(generator_name="__derive__") for name in references},
    }
    configs = [
        ColumnConfig(name="result", derive_from="source", expression=expression),
        *[ColumnConfig(name=name, derive_from="source", expression="value * 10") for name in references],
    ]
    nodes = ColumnDAG().build(specs, configs)
    result = next(node for node in nodes if node.name == "result")
    assert result.depends_on == ["source", *references]
    assert result.derive_from_sources == ["source"]
    names = [node.name for node in nodes]
    for name in references:
        assert names.index(name) < names.index("result")


def test_implicit_dependencies_preserve_explicit_list_sources() -> None:
    specs = {name: GeneratorSpec(generator_name="integer") for name in ("source", "other", "result", "later")}
    configs = [
        ColumnConfig(name="result", derive_from=["source", "other"], expression='sum(value) + row ["later"]'),
        ColumnConfig(name="later", derive_from="source", expression="value * 10"),
    ]
    nodes = ColumnDAG().build(specs, configs)
    result = next(node for node in nodes if node.name == "result")
    assert result.depends_on == ["source", "other", "later"]
    assert result.derive_from_sources == ["source", "other"]
    names = [node.name for node in nodes]
    assert names.index("later") < names.index("result")


def test_genuine_row_reference_cycle_is_still_rejected() -> None:
    specs = {name: GeneratorSpec(generator_name="integer") for name in ("source", "result")}
    configs = [ColumnConfig(name="result", derive_from="source", expression='value + (row) ["result"]')]
    with pytest.raises(ValueError, match="Circular dependency"):
        ColumnDAG().build(specs, configs)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('value + row ["later"]', 77),
        ('value + (row)["later"]', 77),
        ("value + len(\"row['result']\")", 20),
        ("value + 1 # row['result']", 8),
    ],
)
def test_derived_row_syntax_preview_matches_fill(tmp_path: Path, expression: str, expected: int) -> None:
    path = tmp_path / "derived.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE samples (source INTEGER, result INTEGER, later INTEGER)")
        db.execute("INSERT INTO samples VALUES (-1, -11, -10)")
    columns = {
        "source": {"generator": "integer", "params": {"min_value": 7, "max_value": 7}},
        "result": {"derive_from": "source", "expression": expression},
        "later": {"derive_from": "source", "expression": "value * 10"},
    }
    with connect(str(path), provider="base", optimize_pragma=False) as orchestrator:
        before = path.read_bytes()
        preview = orchestrator.preview_table("samples", count=3, seed=42, columns=columns)
        assert path.read_bytes() == before
        assert preview == [{"source": 7, "result": expected, "later": 70}] * 3
        result = orchestrator.fill_table("samples", count=3, columns=columns, seed=42, batch_size=2, skip_ai=True)
        assert_empty(result.errors, list)
        assert result.count == 3
        assert result.batch_count == 2
    with sqlite_connection(path) as db:
        assert db.execute("SELECT source, result, later FROM samples ORDER BY rowid").fetchall() == [
            (-1, -11, -10),
            *[(7, expected, 70)] * 3,
        ]
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
