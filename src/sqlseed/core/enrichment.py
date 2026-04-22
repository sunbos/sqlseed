from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import ColumnMapper, GeneratorSpec

if TYPE_CHECKING:
    from sqlseed.core.schema import SchemaInferrer
    from sqlseed.database._protocol import DatabaseAdapter

logger = get_logger(__name__)


class EnrichmentEngine:
    ENUM_NAME_PATTERNS: ClassVar[list[str]] = [
        r"^[bB]y[A-Za-z]",
        r".*_type$",
        r".*_status$",
        r"^is_.*",
        r"^has_.*",
        r"^can_.*",
        r".*_level$",
        r".*_category$",
        r".*_class$",
        r".*_flag$",
        r".*_kind$",
        r".*_grade$",
        r".*_rank$",
        r".*_tier$",
        r".*_mode$",
        r".*_stage$",
        r".*_phase$",
        r".*_state$",
        r".*_group$",
    ]

    SMALL_INT_TYPES: ClassVar[tuple[str, ...]] = ("INT8", "INT16", "TINYINT", "SMALLINT")

    def __init__(self, db: DatabaseAdapter, mapper: ColumnMapper, schema: SchemaInferrer) -> None:
        self._db = db
        self._mapper = mapper
        self._schema = schema

    def is_enumeration_column(
        self,
        col_name: str,
        col_info: Any,
        distinct_count: int,
        total_rows: int,
        is_unique: bool,
    ) -> bool:
        if is_unique:
            return False
        if total_rows == 0 or distinct_count == 0:
            return False
        cardinality_ratio = distinct_count / total_rows
        name_matches_enum = any(re.match(p, col_name) for p in self.ENUM_NAME_PATTERNS)
        col_type_upper = col_info.type.upper() if col_info and hasattr(col_info, "type") else ""
        is_small_int = any(t in col_type_upper for t in self.SMALL_INT_TYPES)
        return (
            (name_matches_enum and cardinality_ratio < 0.1)
            or (is_small_int and cardinality_ratio < 0.1)
            or (distinct_count <= 10 and cardinality_ratio < 0.05)
            or (
                distinct_count <= 30
                and cardinality_ratio < 0.01
                and "CHAR" not in col_type_upper
                and "TEXT" not in col_type_upper
            )
        )

    def apply(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
        column_infos: list[Any],
        unique_columns: set[str] | None = None,
    ) -> dict[str, GeneratorSpec]:
        has_enrich = any(s.generator_name == "__enrich__" for s in specs.values())
        if not has_enrich:
            return specs

        unique_columns = unique_columns or set()
        row_count = self._db.get_row_count(table_name)
        if row_count == 0:
            for col_name, spec in specs.items():
                if spec.generator_name == "__enrich__":
                    specs[col_name] = GeneratorSpec(generator_name="skip")
            return specs

        for col_name, spec in list(specs.items()):
            if spec.generator_name != "__enrich__":
                continue
            is_unique = col_name in unique_columns
            specs[col_name] = self._build_enriched_spec(table_name, col_name, spec, column_infos, is_unique)

        return specs

    def _calculate_null_ratio(self, values: list[Any], col_info: Any, is_unique: bool) -> tuple[float, list[Any]]:
        null_count = sum(1 for v in values if v is None)
        non_null_values = [v for v in values if v is not None]
        null_ratio = round(null_count / len(values), 3) if values else 0.0

        if col_info and not col_info.nullable:
            null_ratio = 0.0

        if is_unique:
            null_ratio = 0.0

        return null_ratio, non_null_values

    def _build_enriched_spec(
        self,
        table_name: str,
        col_name: str,
        _spec: GeneratorSpec,
        column_infos: list[Any],
        is_unique: bool = False,
    ) -> GeneratorSpec:
        col_info = next((c for c in column_infos if c.name == col_name), None)

        try:
            values = self._db.get_column_values(table_name, col_name, limit=10000)
        except (ValueError, OSError, RuntimeError):
            return GeneratorSpec(generator_name="skip")

        if not values:
            return GeneratorSpec(generator_name="skip")

        null_ratio, non_null_values = self._calculate_null_ratio(values, col_info, is_unique)

        if not non_null_values:
            return GeneratorSpec(generator_name="skip")

        distinct_values = list(set(non_null_values))
        distinct_count = len(distinct_values)
        row_count = self._db.get_row_count(table_name)

        if self.is_enumeration_column(col_name, col_info, distinct_count, row_count, is_unique):
            choices = distinct_values
            if col_info and "INT" in col_info.type.upper():
                choices = [int(v) if isinstance(v, (int, float, str)) else v for v in choices]
            return GeneratorSpec(
                generator_name="choice",
                params={"choices": choices},
                null_ratio=null_ratio,
            )

        if col_info:
            fallback_spec = self._mapper.map_column(col_info, force_type_infer=True)
            if fallback_spec.generator_name != "skip":
                return GeneratorSpec(
                    generator_name=fallback_spec.generator_name,
                    params=fallback_spec.params,
                    null_ratio=null_ratio,
                    provider=fallback_spec.provider,
                )

        return GeneratorSpec(generator_name="skip")
