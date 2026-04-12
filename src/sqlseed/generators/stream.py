from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlseed.core.mapper import GeneratorSpec


class DataStream:
    def __init__(
        self,
        generator_specs: dict[str, GeneratorSpec],
        provider: Any,
        seed: int | None = None,
    ) -> None:
        self._specs = generator_specs
        self._provider = provider
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
        row: dict[str, Any] = {}
        for column_name, spec in self._specs.items():
            if spec.generator_name == "skip":
                continue
            row[column_name] = self._apply_generator(spec)
        return row

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
