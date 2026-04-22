from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed.generators._protocol import UnknownGeneratorError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlseed.core.column_dag import ColumnNode
    from sqlseed.core.constraints import ConstraintSolver
    from sqlseed.core.expression import ExpressionEngine
    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.core.transform import RowTransformFn

logger = get_logger(__name__)


class DataStream:
    def __init__(
        self,
        dag_nodes: list[ColumnNode],
        provider: Any,
        expr_engine: ExpressionEngine,
        constraint_solver: ConstraintSolver,
        transform_fn: RowTransformFn | None = None,
        seed: int | None = None,
    ) -> None:
        self._nodes = dag_nodes
        self._provider = provider
        self._expr_engine = expr_engine
        self._constraint_solver = constraint_solver
        self._transform_fn = transform_fn

        self._rng = random.Random(seed)
        if seed is not None:
            self._provider.set_seed(seed)

    def generate(
        self,
        count: int,
        batch_size: int = 5000,
    ) -> Iterator[list[dict[str, Any]]]:
        generated = 0
        while generated < count:
            current_batch_size = min(batch_size, count - generated)
            batch = [self._generate_row(row_idx=generated + i + 1) for i in range(current_batch_size)]
            yield batch
            generated += current_batch_size

    def _generate_node_value(self, node: ColumnNode, row: dict[str, Any]) -> Any:
        if node.is_derived and node.expression:
            ctx = {"row": row, "value": row.get(node.depends_on[0]) if node.depends_on else None}
            return self._expr_engine.evaluate(node.expression, ctx)

        return self._apply_generator(node.generator_spec)

    def _rollback_source_columns(
        self, source_columns: list[str], row: dict[str, Any], generated_values: dict[str, Any]
    ) -> None:
        for bt_col in source_columns:
            if bt_col in generated_values:
                self._constraint_solver.unregister(bt_col, generated_values[bt_col])
                del generated_values[bt_col]
                row.pop(bt_col, None)

    def _attempt_node_generation(
        self, node: ColumnNode, row: dict[str, Any], generated_values: dict[str, Any]
    ) -> tuple[bool, int | None]:
        col_name = node.name
        max_retries = node.constraints.max_retries if node.constraints else 100
        is_unique = node.constraints.unique if node.constraints else False
        source_columns = node.depends_on if node.is_derived else None

        for _ in range(max_retries):
            val = self._generate_node_value(node, row)
            result = self._constraint_solver.try_register(
                col_name,
                val,
                unique=is_unique,
                source_columns=source_columns,
            )

            if result.registered:
                row[col_name] = val
                generated_values[col_name] = val
                return True, None

            if result.need_backtrack and source_columns:
                self._rollback_source_columns(source_columns, row, generated_values)
                bt_idx = self._find_node_index(source_columns[0])
                return False, bt_idx

        return False, None

    def _handle_col_failure(
        self, backtrack_to: int | None, row: dict[str, Any], generated_values: dict[str, Any]
    ) -> None:
        if backtrack_to is None:
            for col, val in generated_values.items():
                self._constraint_solver.unregister(col, val)
            generated_values.clear()
            row.clear()

    def _finalize_row(self, row: dict[str, Any], row_idx: int, total_retries: int) -> dict[str, Any]:
        if self._transform_fn:
            if callable(self._transform_fn):
                ctx = {"row_number": row_idx, "retry_count": total_retries}
                return self._transform_fn(row, ctx)
            logger.warning("transform_fn is not callable, skipping transformation")
        return row

    def _attempt_row_generation(self, row: dict[str, Any], generated_values: dict[str, Any]) -> tuple[bool, int | None]:
        backtrack_to: int | None = None
        for idx, node in enumerate(self._nodes):
            if node.is_skip or (backtrack_to is not None and idx < backtrack_to):
                continue

            col_success, new_backtrack_to = self._attempt_node_generation(node, row, generated_values)

            if new_backtrack_to is not None:
                backtrack_to = new_backtrack_to

            if not col_success:
                self._handle_col_failure(backtrack_to, row, generated_values)
                return False, backtrack_to

        return True, backtrack_to

    def _generate_row(self, *, row_idx: int) -> dict[str, Any]:
        max_total_retries = 1000
        total_retries = 0

        while total_retries < max_total_retries:
            row: dict[str, Any] = {}
            generated_values: dict[str, Any] = {}

            _, backtrack_to = self._attempt_row_generation(row, generated_values)

            if backtrack_to is not None:
                total_retries += 1
                continue

            if generated_values or not any(not n.is_skip for n in self._nodes):
                return self._finalize_row(row, row_idx, total_retries)

            total_retries += 1

        raise RuntimeError("Failed to generate row satisfying all constraints after maximum retries.")

    def _find_node_index(self, col_name: str) -> int | None:
        for i, node in enumerate(self._nodes):
            if node.name == col_name:
                return i
        return None

    def _apply_generator(self, spec: GeneratorSpec) -> Any:
        if spec.null_ratio > 0 and self._rng.random() < spec.null_ratio:
            return None

        try:
            if spec.params:
                return self._provider.generate(spec.generator_name, **spec.params)
            return self._provider.generate(spec.generator_name)
        except UnknownGeneratorError:
            if spec.generator_name == "choice" and "choices" in spec.params:
                return self._rng.choice(spec.params["choices"])

            if spec.generator_name == "foreign_key":
                return self._handle_foreign_key(spec)

            raise

    def _handle_foreign_key(self, spec: GeneratorSpec) -> Any:
        ref_values = spec.params.get("_ref_values", [])
        if ref_values:
            return self._rng.choice(ref_values)
        return self._provider.generate("integer", min_value=1, max_value=spec.params.get("max_ref", 999999))
