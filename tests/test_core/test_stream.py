from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from sqlseed.core.column_dag import ColumnConstraints, ColumnDAG, ColumnNode
from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.stream import _NATIVE_MISS, DataStream
from sqlseed.generators import UnknownGeneratorError
from sqlseed.generators._protocol import ConfigurationError, GenerationError
from sqlseed.generators.base_provider import BaseProvider


class TestDataStream:
    def _create_stream(self, specs: Any, seed: int = 42) -> Any:
        dag = ColumnDAG()
        nodes = dag.build(specs)
        return DataStream(
            dag_nodes=nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=seed,
        )

    def test_generate_single_batch(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name"),
            "email": GeneratorSpec(generator_name="email"),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert len(batches) == 1
        assert len(batches[0]) == 10
        assert "name" in batches[0][0]
        assert "email" in batches[0][0]

    def test_generate_multiple_batches(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name"),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(15, batch_size=5))
        assert len(batches) == 3
        assert len(batches[0]) == 5
        assert len(batches[1]) == 5
        assert len(batches[2]) == 5

    def test_skip_autoincrement(self) -> None:
        specs = {
            "id": GeneratorSpec(generator_name="skip"),
            "name": GeneratorSpec(generator_name="name"),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert "id" not in batches[0][0]
        assert "name" in batches[0][0]

    def test_null_ratio(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name", null_ratio=1.0),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert all(row["name"] is None for row in batches[0])

    def test_seed_reproducibility(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name"),
            "age": GeneratorSpec(generator_name="integer", params={"min_value": 18, "max_value": 65}),
        }
        stream1 = self._create_stream(specs, seed=42)
        batches1 = list(stream1.generate(5, batch_size=5))

        stream2 = self._create_stream(specs, seed=42)
        batches2 = list(stream2.generate(5, batch_size=5))

        assert batches1[0] == batches2[0]

    def test_choice_generator(self) -> None:
        specs = {
            "status": GeneratorSpec(
                generator_name="choice",
                params={"choices": [0, 1, 2]},
            ),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert all(row["status"] in {0, 1, 2} for row in batches[0])

    def test_foreign_key_with_ref_values(self) -> None:
        specs = {
            "user_id": GeneratorSpec(
                generator_name="foreign_key",
                params={"_ref_values": [1, 2, 3, 4, 5]},
            ),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert all(row["user_id"] in {1, 2, 3, 4, 5} for row in batches[0])

    def test_foreign_key_without_ref_values(self) -> None:
        specs = {
            "user_id": GeneratorSpec(
                generator_name="foreign_key",
                params={"max_ref": 100},
            ),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert all(isinstance(row["user_id"], int) for row in batches[0])

    def test_generator_with_no_params(self) -> None:
        specs = {
            "active": GeneratorSpec(generator_name="boolean"),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert all(isinstance(row["active"], bool) for row in batches[0])

    def test_unknown_generator_raises_error(self) -> None:
        specs = {
            "field": GeneratorSpec(
                generator_name="nonexistent_generator",
                params={"min_length": 5, "max_length": 10},
            ),
        }
        stream = self._create_stream(specs, seed=42)
        with pytest.raises(UnknownGeneratorError, match="Unknown generator 'nonexistent_generator'"):
            list(stream.generate(5, batch_size=5))

    def test_generate_with_unique_constraint(self) -> None:
        specs = {
            "code": GeneratorSpec(
                generator_name="string",
                params={"min_length": 8, "max_length": 8, "charset": "alphanumeric"},
            ),
        }
        dag = ColumnDAG()
        nodes = dag.build(specs)
        unique_nodes = []
        for n in nodes:
            if n.name == "code":
                unique_nodes.append(
                    ColumnNode(
                        name=n.name,
                        generator_spec=n.generator_spec,
                        constraints=ColumnConstraints(unique=True, max_retries=100),
                    )
                )
            else:
                unique_nodes.append(n)
        stream = DataStream(
            dag_nodes=unique_nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        batches = list(stream.generate(10, batch_size=10))
        codes = [row["code"] for row in batches[0]]
        assert len(codes) == len(set(codes))

    def test_generate_max_retries_exceeded(self) -> None:
        nodes = [
            ColumnNode(
                name="col",
                generator_spec=GeneratorSpec(
                    generator_name="integer",
                    params={"min_value": 1, "max_value": 1},
                ),
                constraints=ColumnConstraints(unique=True, max_retries=2),
            )
        ]
        provider = BaseProvider()
        stream = DataStream(
            dag_nodes=nodes,
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        with pytest.raises(RuntimeError, match="Failed to generate row satisfying all constraints after"):
            next(stream.generate(3))

    def test_unknown_generator_error_defined(self) -> None:
        err = UnknownGeneratorError("bad_gen", column_name="col_x")
        assert "bad_gen" in str(err)
        assert "col_x" in str(err)


class TestExpressionErrorPaths:
    """Tests for expression evaluation error handling in _generate_node_value."""

    def _make_derived_node(
        self,
        name: str,
        expression: str,
        depends_on: list[str] | None = None,
    ) -> ColumnNode:
        return ColumnNode(
            name=name,
            generator_spec=GeneratorSpec(generator_name="__derive__"),
            depends_on=depends_on or [],
            expression=expression,
            is_derived=True,
        )

    def test_expression_value_error_raises_generation_error(self) -> None:
        # ValueError in expression → GenerationError
        node = self._make_derived_node("derived", "int('not_a_number')")
        stream = DataStream(
            dag_nodes=[node],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        with pytest.raises(GenerationError, match="Expression evaluation failed"):
            stream._generate_node_value(node, {"row": {}, "value": None})

    def test_expression_syntax_error_raises_generation_error(self) -> None:
        node = self._make_derived_node("derived", "value +")
        stream = DataStream(
            dag_nodes=[node],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        with pytest.raises(GenerationError, match="Expression evaluation failed"):
            stream._generate_node_value(node, {"row": {}, "value": None})

    def test_expression_type_error_raises_configuration_error(self) -> None:
        # TypeError in expression → ConfigurationError
        node = self._make_derived_node("derived", "value + 1")
        stream = DataStream(
            dag_nodes=[node],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        # value is None → None + 1 raises TypeError
        with pytest.raises(ConfigurationError, match="Expression misconfigured"):
            stream._generate_node_value(node, {"row": {}, "value": None})


class TestGeneratorErrorPaths:
    """Tests for generator misconfiguration and value errors."""

    def test_generator_type_error_raises_configuration_error(self) -> None:
        # Provider.generate raises TypeError → ConfigurationError
        node = ColumnNode(
            name="col",
            generator_spec=GeneratorSpec(generator_name="integer", params={"min_value": "not_a_number"}),
        )
        provider = MagicMock()
        provider.generate.side_effect = TypeError("bad type")
        stream = DataStream(
            dag_nodes=[node],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        with pytest.raises(ConfigurationError, match="Generator 'integer' misconfigured"):
            stream._generate_node_value(node, {})

    def test_generator_value_error_raises_generation_error(self) -> None:
        node = ColumnNode(
            name="col",
            generator_spec=GeneratorSpec(generator_name="integer"),
        )
        provider = MagicMock()
        provider.generate.side_effect = ValueError("bad value")
        stream = DataStream(
            dag_nodes=[node],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        with pytest.raises(GenerationError, match="Generator 'integer' value error"):
            stream._generate_node_value(node, {})

    def test_generator_overflow_error_raises_generation_error(self) -> None:
        node = ColumnNode(
            name="col",
            generator_spec=GeneratorSpec(generator_name="integer"),
        )
        provider = MagicMock()
        provider.generate.side_effect = OverflowError("too big")
        stream = DataStream(
            dag_nodes=[node],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        with pytest.raises(GenerationError, match="Generator 'integer' value error"):
            stream._generate_node_value(node, {})

    def test_generator_attribute_error_raises_configuration_error(self) -> None:
        node = ColumnNode(
            name="col",
            generator_spec=GeneratorSpec(generator_name="integer"),
        )
        provider = MagicMock()
        provider.generate.side_effect = AttributeError("missing attr")
        stream = DataStream(
            dag_nodes=[node],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        with pytest.raises(ConfigurationError, match="Generator 'integer' misconfigured"):
            stream._generate_node_value(node, {})


class TestRollbackSourceColumns:
    """Tests for _rollback_source_columns logic."""

    def test_rollback_unregisters_and_removes_values(self) -> None:
        solver = ConstraintSolver()
        solver._register("src1", "val1")
        solver._register("src2", "val2")

        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=solver,
            seed=42,
        )
        row = {"src1": "val1", "src2": "val2", "other": "keep"}
        generated = {"src1": "val1", "src2": "val2"}
        stream._rollback_source_columns(["src1", "src2"], row, generated)

        # Source columns removed from both row and generated_values
        assert "src1" not in row
        assert "src2" not in row
        assert "src1" not in generated
        assert "src2" not in generated
        # Other columns preserved
        assert row["other"] == "keep"

    def test_rollback_skips_columns_not_in_generated(self) -> None:
        solver = ConstraintSolver()
        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=solver,
            seed=42,
        )
        row = {"src1": "val1"}
        generated = {"src1": "val1"}
        # src2 not in generated_values — should not raise
        stream._rollback_source_columns(["src1", "src2"], row, generated)
        assert "src1" not in row
        assert "src1" not in generated

    def test_rollback_unregisters_from_constraint_solver(self) -> None:
        solver = ConstraintSolver()
        solver._register("col", "val")
        assert solver._is_seen("col", "val")

        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=solver,
            seed=42,
        )
        stream._rollback_source_columns(["col"], {"col": "val"}, {"col": "val"})
        # Value should be unregistered
        assert not solver._is_seen("col", "val")


class TestAttemptNodeGeneration:
    """Tests for _attempt_node_generation retry and backtracking logic."""

    def test_generation_error_returns_failure(self) -> None:
        # When _generate_node_value raises GenerationError, return (False, None)
        node = ColumnNode(
            name="col",
            generator_spec=GeneratorSpec(generator_name="integer"),
            constraints=ColumnConstraints(unique=False, max_retries=3),
        )
        provider = MagicMock()
        provider.generate.side_effect = ValueError("fail")
        stream = DataStream(
            dag_nodes=[node],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        success, backtrack_to = stream._attempt_node_generation(node, {}, {})
        assert success is False
        assert backtrack_to is None

    def test_backtrack_triggered_for_derived_unique_column(self) -> None:
        # When unique constraint violated on derived column, backtrack is triggered
        solver = ConstraintSolver()
        # Pre-register a value so the next attempt collides
        solver._register("derived", "existing")

        node = ColumnNode(
            name="derived",
            generator_spec=GeneratorSpec(generator_name="string", params={"min_length": 3, "max_length": 3}),
            depends_on=["src"],
            expression=None,
            is_derived=True,
            constraints=ColumnConstraints(unique=True, max_retries=5),
        )
        # Build a stream with src node first, then derived
        src_node = ColumnNode(
            name="src",
            generator_spec=GeneratorSpec(generator_name="string", params={"min_length": 3, "max_length": 3}),
        )
        stream = DataStream(
            dag_nodes=[src_node, node],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=solver,
            seed=42,
        )
        # Force the generator to produce "existing" to trigger collision
        # We do this by making the generated value collide
        row = {"src": "src_val"}
        generated = {"src": "src_val"}
        # Mock _generate_node_value to return "existing"
        original = stream._generate_node_value
        stream._generate_node_value = lambda n, r: "existing"  # type: ignore[method-assign]
        try:
            success, backtrack_to = stream._attempt_node_generation(node, row, generated)
        finally:
            stream._generate_node_value = original  # type: ignore[method-assign]
        assert success is False
        assert backtrack_to is not None
        # Backtrack target should be the index of "src"
        assert backtrack_to == 0


class TestHandleColFailure:
    """Tests for _handle_col_failure."""

    def test_clears_all_values_when_no_backtrack(self) -> None:
        solver = ConstraintSolver()
        solver._register("col1", "val1")
        solver._register("col2", "val2")

        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=solver,
            seed=42,
        )
        row = {"col1": "val1", "col2": "val2"}
        generated = {"col1": "val1", "col2": "val2"}
        stream._handle_col_failure(None, row, generated)

        assert row == {}
        assert generated == {}
        # Values unregistered from solver
        assert not solver._is_seen("col1", "val1")
        assert not solver._is_seen("col2", "val2")


class TestFinalizeRow:
    """Tests for _finalize_row with various transform_fn scenarios."""

    def test_applies_callable_transform(self) -> None:
        def transform(row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
            row["transformed"] = True
            row["row_number"] = ctx["row_number"]
            row["retry_count"] = ctx["retry_count"]
            return row

        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            transform_fn=transform,
            seed=42,
        )
        row = {"name": "test"}
        result = stream._finalize_row(row, row_idx=5, total_retries=2)
        assert result["transformed"] is True
        assert result["row_number"] == 5
        assert result["retry_count"] == 2

    def test_non_callable_transform_logs_warning(self) -> None:
        # transform_fn is set but not callable → should log warning and return row unchanged
        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            transform_fn="not_callable",  # type: ignore[arg-type]
            seed=42,
        )
        row = {"name": "test"}
        result = stream._finalize_row(row, row_idx=1, total_retries=0)
        assert result == {"name": "test"}

    def test_no_transform_fn_returns_row_unchanged(self) -> None:
        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        row = {"name": "test"}
        result = stream._finalize_row(row, row_idx=1, total_retries=0)
        assert result == {"name": "test"}


class TestFindNodeIndex:
    """Tests for _find_node_index."""

    def test_returns_index_for_existing_column(self) -> None:
        nodes = [
            ColumnNode(name="a", generator_spec=GeneratorSpec(generator_name="string")),
            ColumnNode(name="b", generator_spec=GeneratorSpec(generator_name="string")),
        ]
        stream = DataStream(
            dag_nodes=nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        assert stream._find_node_index("a") == 0
        assert stream._find_node_index("b") == 1

    def test_returns_none_for_missing_column(self) -> None:
        nodes = [ColumnNode(name="a", generator_spec=GeneratorSpec(generator_name="string"))]
        stream = DataStream(
            dag_nodes=nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        assert stream._find_node_index("nonexistent") is None


class TestApplyGenerator:
    """Tests for _apply_generator covering null_ratio, choice fallback, foreign_key fallback."""

    def test_null_ratio_returns_none(self) -> None:
        # null_ratio=1.0 → always returns None
        spec = GeneratorSpec(generator_name="string", null_ratio=1.0)
        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._apply_generator(spec)
        assert result is None

    def test_zero_null_ratio_never_returns_none(self) -> None:
        spec = GeneratorSpec(generator_name="integer", null_ratio=0.0)
        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        for _ in range(20):
            assert stream._apply_generator(spec) is not None

    def test_choice_fallback_on_unknown_generator(self) -> None:
        # When provider doesn't know "choice", fallback to local rng.choice
        spec = GeneratorSpec(
            generator_name="choice",
            params={"choices": [10, 20, 30]},
        )
        provider = MagicMock()
        provider.generate.side_effect = UnknownGeneratorError("choice")
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._apply_generator(spec)
        assert result in {10, 20, 30}

    def test_foreign_key_fallback_with_ref_values(self) -> None:
        spec = GeneratorSpec(
            generator_name="foreign_key",
            params={"_ref_values": [100, 200, 300]},
        )
        provider = MagicMock()
        provider.generate.side_effect = UnknownGeneratorError("foreign_key")
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._apply_generator(spec)
        assert result in {100, 200, 300}

    def test_foreign_key_fallback_without_ref_values(self) -> None:
        # No _ref_values → fallback to provider.generate("integer", ...)
        spec = GeneratorSpec(
            generator_name="foreign_key",
            params={"max_ref": 50},
        )
        provider = MagicMock()
        # First call (foreign_key) raises UnknownGeneratorError
        # Second call (integer) returns a value
        provider.generate.side_effect = [
            UnknownGeneratorError("foreign_key"),
            42,
        ]
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._apply_generator(spec)
        assert result == 42
        # Verify the integer call had correct params
        assert provider.generate.call_count == 2
        second_call = provider.generate.call_args_list[1]
        assert second_call.args[0] == "integer"
        assert second_call.kwargs == {"min_value": 1, "max_value": 50}


class TestTryNativeMethod:
    """Tests for _try_native_method, _try_faker_native, _try_mimesis_native."""

    def test_try_native_returns_miss_when_no_native_config(self) -> None:
        spec = GeneratorSpec(generator_name="string")  # No native methods configured
        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        # _NATIVE_MISS is a private sentinel, compare by identity
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS

    def test_try_faker_native_returns_miss_when_no_faker_attr(self) -> None:
        # BaseProvider has no _faker attribute
        spec = GeneratorSpec(generator_name="string", native_faker_method="email")
        stream = DataStream(
            dag_nodes=[],
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS

    def test_try_faker_native_calls_method_when_available(self) -> None:
        # Provider with _faker attribute
        fake_faker = MagicMock()
        fake_faker.email.return_value = "test@example.com"
        provider = MagicMock()
        provider.name = "faker"
        provider._faker = fake_faker

        spec = GeneratorSpec(
            generator_name="string",
            native_faker_method="email",
            native_params={"domain": "example.com"},
        )
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result == "test@example.com"
        fake_faker.email.assert_called_once_with(domain="example.com")

    def test_try_faker_native_returns_miss_on_type_error(self) -> None:
        fake_faker = MagicMock()
        fake_faker.email.side_effect = TypeError("bad args")
        provider = MagicMock()
        provider.name = "faker"
        provider._faker = fake_faker

        spec = GeneratorSpec(generator_name="string", native_faker_method="email")
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS

    def test_try_faker_native_returns_miss_when_method_not_found(self) -> None:
        fake_faker = MagicMock()
        # Configure so getattr returns None for the missing method
        del fake_faker.nonexistent_method
        provider = MagicMock()
        provider.name = "faker"
        provider._faker = fake_faker

        spec = GeneratorSpec(generator_name="string", native_faker_method="nonexistent_method")
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS

    def test_try_faker_native_returns_miss_on_value_error(self) -> None:
        fake_faker = MagicMock()
        fake_faker.email.side_effect = ValueError("bad value")
        provider = MagicMock()
        provider.name = "faker"
        provider._faker = fake_faker

        spec = GeneratorSpec(generator_name="string", native_faker_method="email")
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS

    def test_try_mimesis_native_returns_miss_when_no_generic_attr(self) -> None:
        provider = MagicMock()
        provider.name = "mimesis"
        # Remove _generic to simulate missing attribute
        del provider._generic

        spec = GeneratorSpec(
            generator_name="string",
            native_mimesis_method="person.full_name",
        )
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS

    def test_try_mimesis_native_walks_dotted_path(self) -> None:
        # Set up a nested object structure: generic.person.full_name()
        generic = MagicMock()
        generic.person.full_name.return_value = "John Doe"
        provider = MagicMock()
        provider.name = "mimesis"
        provider._generic = generic

        spec = GeneratorSpec(
            generator_name="string",
            native_mimesis_method="person.full_name",
            native_params={},
        )
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result == "John Doe"
        generic.person.full_name.assert_called_once_with()

    def test_try_mimesis_native_returns_miss_on_invalid_path(self) -> None:
        # Path component doesn't exist → returns _NATIVE_MISS
        generic = MagicMock()
        del generic.nonexistent
        provider = MagicMock()
        provider.name = "mimesis"
        provider._generic = generic

        spec = GeneratorSpec(
            generator_name="string",
            native_mimesis_method="nonexistent.method",
        )
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS

    def test_try_mimesis_native_returns_miss_on_type_error(self) -> None:
        generic = MagicMock()
        generic.person.full_name.side_effect = TypeError("bad args")
        provider = MagicMock()
        provider.name = "mimesis"
        provider._generic = generic

        spec = GeneratorSpec(
            generator_name="string",
            native_mimesis_method="person.full_name",
        )
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS

    def test_try_mimesis_native_returns_miss_on_value_error(self) -> None:
        generic = MagicMock()
        generic.person.full_name.side_effect = ValueError("bad value")
        provider = MagicMock()
        provider.name = "mimesis"
        provider._generic = generic

        spec = GeneratorSpec(
            generator_name="string",
            native_mimesis_method="person.full_name",
        )
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS

    def test_try_mimesis_native_returns_miss_when_final_obj_not_callable(self) -> None:
        # Final attribute is not callable
        generic = MagicMock()
        generic.person.full_name = "not_callable_string"
        provider = MagicMock()
        provider.name = "mimesis"
        provider._generic = generic

        spec = GeneratorSpec(
            generator_name="string",
            native_mimesis_method="person.full_name",
        )
        stream = DataStream(
            dag_nodes=[],
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        result = stream._try_native_method(spec)
        assert result is _NATIVE_MISS


class TestGenerateRowBacktracking:
    """Tests for _generate_row backtracking and retry logic."""

    def test_derived_column_with_backtracking_succeeds(self) -> None:
        # Derived column depends on src; when derived collides, src should be regenerated
        # Build a scenario where backtracking is needed but eventually succeeds
        dag = ColumnDAG()
        nodes = dag.build(
            {
                "base": GeneratorSpec(generator_name="integer", params={"min_value": 1, "max_value": 100}),
                "derived": GeneratorSpec(generator_name="__derive__"),
            },
        )
        # Manually set up derived node
        for i, n in enumerate(nodes):
            if n.name == "derived":
                nodes[i] = ColumnNode(
                    name="derived",
                    generator_spec=GeneratorSpec(generator_name="__derive__"),
                    depends_on=["base"],
                    expression="value + 1",
                    is_derived=True,
                    constraints=ColumnConstraints(unique=True, max_retries=10),
                )
        stream = DataStream(
            dag_nodes=nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        row = stream._generate_row(row_idx=1)
        assert "base" in row
        assert "derived" in row
        assert row["derived"] == row["base"] + 1

    def test_generate_row_with_all_skip_nodes_returns_empty_row(self) -> None:
        # All nodes are skip → should return empty row without infinite loop
        nodes = [
            ColumnNode(
                name="id",
                generator_spec=GeneratorSpec(generator_name="skip"),
            ),
        ]
        stream = DataStream(
            dag_nodes=nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        row = stream._generate_row(row_idx=1)
        assert row == {}


class TestGenerateBatchSize:
    """Tests for batch size edge cases in generate()."""

    def test_generate_count_zero(self) -> None:
        specs = {"name": GeneratorSpec(generator_name="name")}
        dag = ColumnDAG()
        nodes = dag.build(specs)
        stream = DataStream(
            dag_nodes=nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        batches = list(stream.generate(0, batch_size=10))
        assert batches == []

    def test_generate_batch_larger_than_count(self) -> None:
        specs = {"name": GeneratorSpec(generator_name="name")}
        dag = ColumnDAG()
        nodes = dag.build(specs)
        stream = DataStream(
            dag_nodes=nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        batches = list(stream.generate(3, batch_size=100))
        assert len(batches) == 1
        assert len(batches[0]) == 3
