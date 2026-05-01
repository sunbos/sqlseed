from __future__ import annotations

import pytest

from sqlseed.config.models import ColumnConfig, ColumnConstraintsConfig
from sqlseed.core.column_dag import ColumnDAG, ColumnNode
from sqlseed.core.mapper import GeneratorSpec


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
            "card_number": GeneratorSpec(generator_name="string"),
            "last_eight": GeneratorSpec(generator_name="__derive__"),
        }
        configs = [
            ColumnConfig(name="card_number", generator="string"),
            ColumnConfig(name="last_eight", derive_from="card_number", expression="value[-8:]"),
        ]
        dag = ColumnDAG()
        nodes = dag.build(specs, configs)
        names = [n.name for n in nodes]
        assert names.index("card_number") < names.index("last_eight")
        last_eight_node = next(n for n in nodes if n.name == "last_eight")
        assert last_eight_node.is_derived is True
        assert last_eight_node.depends_on == ["card_number"]
        assert last_eight_node.expression == "value[-8:]"

    def test_build_with_unique_constraint(self) -> None:
        specs = {
            "email": GeneratorSpec(generator_name="email"),
            "name": GeneratorSpec(generator_name="string"),
        }
        dag = ColumnDAG()
        nodes = dag.build(specs, unique_columns={"email"})
        email_node = next(n for n in nodes if n.name == "email")
        assert email_node.constraints is not None
        assert email_node.constraints.unique is True

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
        assert age_node.constraints.unique is True
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
