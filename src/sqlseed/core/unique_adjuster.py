from __future__ import annotations

import math
from typing import TYPE_CHECKING

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import ColumnMapper, GeneratorSpec

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo

logger = get_logger(__name__)


class UniqueAdjuster:
    def __init__(self, mapper: ColumnMapper) -> None:
        self._mapper = mapper

    def adjust(
        self,
        specs: dict[str, GeneratorSpec],
        unique_columns: set[str],
        count: int,
        column_infos: list[ColumnInfo] | None = None,
    ) -> dict[str, GeneratorSpec]:
        for col_name in unique_columns:
            if col_name not in specs:
                continue
            spec = specs[col_name]
            if spec.generator_name == "skip":
                continue

            if spec.generator_name == "string":
                specs[col_name] = self._adjust_string(spec, col_name, count, column_infos)
            elif spec.generator_name == "integer":
                specs[col_name] = self._adjust_integer(spec, col_name, count, column_infos)
            elif spec.generator_name == "choice":
                specs = self._adjust_choice(specs, spec, col_name, count, column_infos)

        return specs

    def _adjust_string(
        self,
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        _column_infos: list[ColumnInfo] | None,
    ) -> GeneratorSpec:
        params = dict(spec.params)
        charset_size = 62
        if params.get("charset") == "digits":
            charset_size = 10
        elif params.get("charset") == "alpha":
            charset_size = 52

        max_length = params.get("max_length", 50)
        min_needed = max(1, math.ceil(math.log(max(count * count * 50, 1)) / math.log(charset_size)))
        current_min = params.get("min_length", 1)
        params["min_length"] = max(current_min, min_needed)

        if params["min_length"] > max_length:
            if params.get("charset") is None:
                params["charset"] = "alphanumeric"
                charset_size = 62
                min_needed = max(1, math.ceil(math.log(max(count * count * 50, 1)) / math.log(charset_size)))
                params["min_length"] = max(current_min, min_needed)
            if params["min_length"] > max_length:
                logger.warning(
                    "Cannot guarantee uniqueness for VARCHAR(%d) with count=%d",
                    max_length,
                    count,
                    column=col_name,
                )
                params["max_length"] = max(params["min_length"], max_length)
        elif params["max_length"] < params["min_length"]:
            params["max_length"] = params["min_length"]

        return GeneratorSpec(
            generator_name=spec.generator_name,
            params=params,
            null_ratio=spec.null_ratio,
            provider=spec.provider,
        )

    def _adjust_integer(
        self,
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        column_infos: list[ColumnInfo] | None,
    ) -> GeneratorSpec:
        params = dict(spec.params)
        min_val = params.get("min_value", 0)
        max_val = params.get("max_value", 999999)
        if max_val - min_val < count * 10:
            col_info = next((c for c in (column_infos or []) if c.name == col_name), None)
            if col_info:
                col_type_upper = col_info.type.upper()
                if "INT8" in col_type_upper and count > 255:
                    logger.warning(
                        "INT8 column with UNIQUE constraint cannot guarantee uniqueness for count > 255",
                        column=col_name,
                        count=count,
                    )
                elif "INT16" in col_type_upper and count > 65535:
                    logger.warning(
                        "INT16 column with UNIQUE constraint cannot guarantee uniqueness for count > 65535",
                        column=col_name,
                        count=count,
                    )
            params["max_value"] = min_val + count * 10
        return GeneratorSpec(
            generator_name=spec.generator_name,
            params=params,
            null_ratio=spec.null_ratio,
            provider=spec.provider,
        )

    def _adjust_choice(
        self,
        specs: dict[str, GeneratorSpec],
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        column_infos: list[ColumnInfo] | None,
    ) -> dict[str, GeneratorSpec]:
        choices = spec.params.get("choices", [])
        if len(choices) < count:
            col_info = None
            if column_infos:
                col_info = next((c for c in column_infos if c.name == col_name), None)
            if col_info:
                fallback = self._mapper.map_column(col_info, force_type_infer=True)
                if fallback.generator_name not in ("skip", "choice"):
                    specs[col_name] = GeneratorSpec(
                        generator_name=fallback.generator_name,
                        params=fallback.params,
                        null_ratio=spec.null_ratio,
                        provider=fallback.provider,
                    )
                    specs = self.adjust(specs, {col_name}, count, column_infos)
        return specs
