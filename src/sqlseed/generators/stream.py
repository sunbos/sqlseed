from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.core.column_dag import ColumnNode
    from sqlseed.core.expression import ExpressionEngine
    from sqlseed.core.constraints import ConstraintSolver
    from sqlseed.core.transform import RowTransformFn


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
            batch = [self._generate_row() for _ in range(current_batch_size)]
            yield batch
            generated += current_batch_size

    def _generate_row(self) -> dict[str, Any]:
        max_total_retries = 1000
        total_retries = 0

        while total_retries < max_total_retries:
            row: dict[str, Any] = {}
            generated_values: dict[str, Any] = {}
            success = True

            for node in self._nodes:
                if node.is_skip:
                    continue

                col_name = node.name
                max_retries = node.constraints.max_retries if node.constraints else 100
                is_unique = node.constraints.unique if node.constraints else False

                col_success = False
                for _ in range(max_retries):
                    if node.is_derived and node.expression:
                        ctx = {"row": row, "value": row.get(node.depends_on[0]) if node.depends_on else None}
                        val = self._expr_engine.evaluate(node.expression, ctx)
                    else:
                        val = self._apply_generator(node.generator_spec)

                    if self._constraint_solver.check_and_register(col_name, val, unique=is_unique):
                        row[col_name] = val
                        generated_values[col_name] = val
                        col_success = True
                        break

                if not col_success:
                    success = False
                    break

            if success:
                if self._transform_fn:
                    ctx = {"row_number": total_retries}
                    row = self._transform_fn(row, ctx)
                return row

            for col_name, val in generated_values.items():
                self._constraint_solver.unregister(col_name, val)

            total_retries += 1

        raise RuntimeError("Failed to generate row satisfying all constraints after maximum retries.")

    def _apply_generator(self, spec: GeneratorSpec) -> Any:
        if spec.null_ratio > 0 and self._rng.random() < spec.null_ratio:
            return None

        method_name = f"generate_{spec.generator_name}"
        if hasattr(self._provider, method_name):
            method = getattr(self._provider, method_name)
            return method(**spec.params) if spec.params else method()

        if spec.generator_name == "choice" and "choices" in spec.params:
            return self._rng.choice(spec.params["choices"])

        if spec.generator_name == "foreign_key":
            return self._handle_foreign_key(spec)

        return self._provider.generate_string(**spec.params) if spec.params else self._provider.generate_string()

    def _handle_foreign_key(self, spec: GeneratorSpec) -> Any:
        ref_values = spec.params.get("_ref_values", [])
        if ref_values:
            return self._rng.choice(ref_values)
        return self._provider.generate_integer(min_value=1, max_value=spec.params.get("max_ref", 999999))
