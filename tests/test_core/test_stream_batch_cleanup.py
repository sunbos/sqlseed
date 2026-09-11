"""Discarded batches release only their own pre-transform unique registrations."""

from __future__ import annotations

from typing import Any

import pytest

from sqlseed.core.column_dag import ColumnConstraints, ColumnNode
from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.stream import DataStream, GenerationBudgetExceededError, GenerationCancelledError
from sqlseed.generators.base_provider import BaseProvider


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5])
def test_invalid_batch_size_is_rejected_without_yielding(batch_size: Any) -> None:
    stream = DataStream([], BaseProvider(), ExpressionEngine(), ConstraintSolver(), max_attempts=1)
    with pytest.raises(ValueError, match="batch_size"):
        next(stream.generate(1, batch_size=batch_size))


@pytest.mark.parametrize("stop", ["cancel", "budget"])
def test_discarded_batch_releases_original_keys_but_keeps_delivered_batch(stop: str) -> None:
    solver = ConstraintSolver()
    calls = 0
    rows = 0

    def guard() -> None:
        nonlocal calls
        calls += 1
        if stop == "cancel" and calls == 11:
            raise ValueError("stop before third row")

    def transform(row: dict[str, Any], context: Any) -> dict[str, Any]:
        nonlocal rows
        rows += 1
        row["code"] = "transformed"
        return row

    nodes = [
        ColumnNode(
            "code", GeneratorSpec("template", {"template": "{sequence}"}), constraints=ColumnConstraints(is_unique=True)
        ),
        ColumnNode("kind", GeneratorSpec("choice", {"choices": [1]})),
    ]
    stream = DataStream(
        nodes,
        BaseProvider(),
        ExpressionEngine(),
        solver,
        cancel_check=guard,
        max_attempts=6 if stop == "budget" else None,
        transform_fn=transform,
        composite_unique_constraints=[["code", "kind"]],
    )
    assert next(stream.generate(1)) == [{"code": "transformed", "kind": 1}]
    with pytest.raises(GenerationCancelledError if stop == "cancel" else GenerationBudgetExceededError):
        next(stream.generate(2))
    assert rows == 2
    assert not solver.try_register("code", "1", is_unique=True).is_registered
    assert solver.try_register("code", "2", is_unique=True).is_registered
    key = "__composite__('code', 'kind')"
    assert not solver.check_and_register_composite(key, ("1", 1))
    assert solver.check_and_register_composite(key, ("2", 1))


def test_provider_configuration_error_releases_current_partial_row() -> None:
    from sqlseed.generators._protocol import ConfigurationError

    solver = ConstraintSolver()
    bad = GeneratorSpec("integer", {"min_value": 1, "max_value": 1})
    nodes = [
        ColumnNode(
            "code", GeneratorSpec("template", {"template": "{sequence}"}), constraints=ColumnConstraints(is_unique=True)
        ),
        ColumnNode("bad", bad),
    ]
    stream = DataStream(nodes, BaseProvider(), ExpressionEngine(), solver)
    assert next(stream.generate(1)) == [{"code": "1", "bad": 1}]
    bad.params["unsupported"] = True
    with pytest.raises(ConfigurationError):
        next(stream.generate(1))
    assert not solver.try_register("code", "1", is_unique=True).is_registered
    assert solver.try_register("code", "2", is_unique=True).is_registered


def test_constraint_type_error_releases_current_composite_registration() -> None:
    from sqlseed.generators._protocol import ConfigurationError

    solver = ConstraintSolver()
    nodes = [
        ColumnNode("a", GeneratorSpec("choice", {"choices": [1]})),
        ColumnNode("b", GeneratorSpec("choice", {"choices": ["text"]})),
    ]
    stream = DataStream(
        nodes,
        BaseProvider(),
        ExpressionEngine(),
        solver,
        composite_unique_constraints=[["a", "b"]],
        inequality_constraints=[("a", "b", "<")],
    )
    key = "__composite__('a', 'b')"
    assert solver.check_and_register_composite(key, (2, "prior"))
    with pytest.raises(ConfigurationError):
        next(stream.generate(1))
    assert not solver.check_and_register_composite(key, (2, "prior"))
    assert solver.check_and_register_composite(key, (1, "text"))
