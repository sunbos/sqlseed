"""Sample generation can bound retries without changing normal streams."""

from __future__ import annotations

from typing import Any

import pytest

from sqlseed.core import stream as stream_module
from sqlseed.core.column_dag import ColumnConstraints, ColumnNode
from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.mapper import GeneratorSpec
from sqlseed.generators.base_provider import BaseProvider


def make_stream(*, unique: bool = False, **kwargs: Any) -> stream_module.DataStream:
    node = ColumnNode(
        "code", GeneratorSpec("choice", {"choices": ["private-value"]}), constraints=ColumnConstraints(is_unique=unique)
    )
    return stream_module.DataStream([node], BaseProvider(), ExpressionEngine(), ConstraintSolver(), **kwargs)


def test_constant_unique_retries_share_one_stream_budget() -> None:
    stream = make_stream(unique=True, max_attempts=12, table_name="items")
    assert next(stream.generate(1)) == [{"code": "private-value"}]
    with pytest.raises(RuntimeError, match=r"attempt budget.*12") as caught:
        next(stream.generate(1))
    assert type(caught.value) is stream_module.GenerationBudgetExceededError
    assert caught.value.limit == 12
    assert caught.value.table == "items"
    assert caught.value.column == "code"
    assert caught.value.generator == "choice"
    assert "items" in str(caught.value) and "code" in str(caught.value) and "choice" in str(caught.value)
    assert "private-value" not in str(caught.value)


def test_cross_column_row_retries_consume_budget() -> None:
    nodes = [ColumnNode(name, GeneratorSpec("integer", {"min_value": 1, "max_value": 1})) for name in ("a", "b")]
    stream = stream_module.DataStream(
        nodes,
        BaseProvider(),
        ExpressionEngine(),
        ConstraintSolver(),
        inequality_constraints=[("a", "b", "<")],
        max_attempts=9,
    )
    with pytest.raises(RuntimeError, match=r"attempt budget.*9"):
        next(stream.generate(1))


def test_skip_only_rows_cannot_bypass_budget() -> None:
    stream = stream_module.DataStream(
        [ColumnNode("id", GeneratorSpec("skip"))],
        BaseProvider(),
        ExpressionEngine(),
        ConstraintSolver(),
        max_attempts=2,
    )
    batches = stream.generate(3, batch_size=1)
    assert next(batches) == [{}]
    assert next(batches) == [{}]
    with pytest.raises(RuntimeError, match=r"attempt budget.*2"):
        next(batches)


def test_default_stream_and_other_streams_are_unaffected() -> None:
    limited = make_stream(max_attempts=1)
    with pytest.raises(RuntimeError, match="attempt budget"):
        next(limited.generate(1))
    normal = make_stream()
    assert len(next(normal.generate(1001))) == 1001
    assert next(make_stream(max_attempts=2).generate(1)) == [{"code": "private-value"}]


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_attempt_budget_is_rejected(budget: Any) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        make_stream(max_attempts=budget)


def test_cancel_guard_interrupts_unique_retry_and_preserves_reason() -> None:
    reason = ValueError("cancel requested")
    calls = 0

    def cancel_check() -> None:
        nonlocal calls
        calls += 1
        if calls == 8:
            raise reason

    stream = make_stream(unique=True, cancel_check=cancel_check)
    with pytest.raises(RuntimeError) as caught:
        next(stream.generate(2))
    assert type(caught.value) is stream_module.GenerationCancelledError
    assert caught.value.__cause__ is reason
    assert calls == 8


def test_cancel_after_transform_prevents_yielding_the_row() -> None:
    cancelled = False

    def transform(row: dict[str, Any], context: Any) -> dict[str, Any]:
        nonlocal cancelled
        cancelled = True
        return row

    def cancel_check() -> None:
        if cancelled:
            raise ValueError("cancelled by transform")

    stream = stream_module.DataStream(
        [ColumnNode("id", GeneratorSpec("skip"))],
        BaseProvider(),
        ExpressionEngine(),
        ConstraintSolver(),
        transform_fn=transform,
        cancel_check=cancel_check,
    )
    with pytest.raises(RuntimeError, match="cancelled"):
        next(stream.generate(1))


def test_budget_releases_unique_values_from_the_interrupted_row() -> None:
    solver = ConstraintSolver()
    nodes = [
        ColumnNode("a", GeneratorSpec("choice", {"choices": [1]}), constraints=ColumnConstraints(is_unique=True)),
        ColumnNode("b", GeneratorSpec("choice", {"choices": [2]})),
    ]
    stream = stream_module.DataStream(nodes, BaseProvider(), ExpressionEngine(), solver, max_attempts=2)
    with pytest.raises(stream_module.GenerationBudgetExceededError):
        next(stream.generate(1))
    assert solver.try_register("a", 1, is_unique=True).is_registered


def test_cancel_after_transform_releases_composite_and_single_keys() -> None:
    cancelled = False
    transformed = False

    def transform(row: dict[str, Any], context: Any) -> dict[str, Any]:
        nonlocal cancelled, transformed
        if not transformed:
            cancelled = transformed = True
        return row

    def cancel_check() -> None:
        nonlocal cancelled
        if cancelled:
            cancelled = False
            raise ValueError("stop once")

    nodes = [
        ColumnNode("a", GeneratorSpec("choice", {"choices": [1]}), constraints=ColumnConstraints(is_unique=True)),
        ColumnNode("b", GeneratorSpec("choice", {"choices": [2]})),
    ]
    stream = stream_module.DataStream(
        nodes,
        BaseProvider(),
        ExpressionEngine(),
        ConstraintSolver(),
        composite_unique_constraints=[["a", "b"]],
        transform_fn=transform,
        max_attempts=9,
        cancel_check=cancel_check,
    )
    with pytest.raises(stream_module.GenerationCancelledError):
        next(stream.generate(1))
    assert next(stream.generate(1)) == [{"a": 1, "b": 2}]
