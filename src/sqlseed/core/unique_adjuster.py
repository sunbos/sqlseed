"""Uniqueness adjuster: handles retry logic for unique constraint conflicts.

Adjusts generation parameters for string/integer/choice type columns before data generation:
ensures their value space is sufficient to accommodate the target row count: reducing
the probability of unique constraint conflicts.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import ColumnMapper, GeneratorSpec

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo

logger = get_logger(__name__)


class UniqueAdjuster:
    """Uniqueness adjuster: adjusts generator spec parameters for unique constraint columns.

    Based on the target row count and column type: extends string length, integer value
    range, or falls back to type inference for choice columns: to best ensure uniqueness
    of generated values.
    """

    def __init__(self, mapper: ColumnMapper) -> None:
        """Initialize the adjuster: bind a column mapper for choice column fallback inference."""
        self._mapper = mapper

    def adjust(
        self,
        specs: dict[str, GeneratorSpec],
        unique_columns: set[str],
        count: int,
        column_infos: list[ColumnInfo] | None = None,
        check_constraints: list[Any] | None = None,
    ) -> dict[str, GeneratorSpec]:
        """Adjust generator specs by type for the set of unique constraint columns.

        - string: extends the minimum length to satisfy the value space;
        - integer: extends the value range to accommodate the target row count;
        - choice: falls back to type inference and recursively adjusts when choices are insufficient.

        ``check_constraints`` is optional per-table CHECK metadata. When a UNIQUE
        integer column is bounded by a CHECK range (e.g. ``CHECK (age >= 18 AND
        age <= 65)``), the value space is NOT widened beyond the CHECK bounds —
        expanding would generate values that violate the constraint.
        """
        for col_name in unique_columns:
            if col_name not in specs:
                continue
            spec = specs[col_name]
            if spec.generator_name in {"skip", "autoincrement"}:
                # A nullable UNIQUE column (not PK, no DEFAULT) falls through
                # to the L8 nullable-skip fallback and would be silently
                # filled with NULL for every row — valid per SQLite (multiple
                # NULLs are distinct) but semantically useless. Re-map it to
                # a type-faithful generator so it gets real unique values.
                specs = self._adjust_skip_unique(specs, col_name, count, column_infos, check_constraints)
                continue

            if spec.generator_name == "string":
                specs[col_name] = self._adjust_string(spec, col_name, count, column_infos)
            elif spec.generator_name == "integer":
                specs[col_name] = self._adjust_integer(spec, col_name, count, column_infos, check_constraints)
            elif spec.generator_name == "choice":
                specs = self._adjust_choice(specs, spec, col_name, count, column_infos, check_constraints)

        return specs

    def _adjust_skip_unique(
        self,
        specs: dict[str, GeneratorSpec],
        col_name: str,
        count: int,
        column_infos: list[ColumnInfo] | None,
        check_constraints: list[Any] | None,
    ) -> dict[str, GeneratorSpec]:
        """Re-map a nullable UNIQUE column that fell through to the L8 "skip" fallback.

        Only touches columns that are nullable, non-PK, and have no DEFAULT —
        those are the ones where "skip" means a silent all-NULL fill. When the
        type-faithful fallback itself yields "skip"/"autoincrement" (e.g.,
        unresolvable types), the original spec is kept untouched.
        """
        col_info = next((c for c in (column_infos or []) if c.name == col_name), None)
        if col_info is None:
            return specs
        if col_info.is_primary_key or col_info.default is not None or not col_info.nullable:
            return specs
        fallback = self._mapper.map_column(col_info, force_type_infer=True)
        if fallback.generator_name in {"skip", "autoincrement"}:
            return specs
        # Clamp integer fallbacks to CHECK-bounded ranges BEFORE assigning, so
        # a UNIQUE nullable integer column (e.g. ``qty INTEGER UNIQUE CHECK
        # (qty >= 1 AND qty <= 100)``) never gets a widened [0, 999999] range
        # that generates CHECK-violating values. The type-faithful fallback
        # knows nothing about CHECK constraints, so without this clamp the
        # wide range would be kept (space large enough for uniqueness) and
        # every value would still violate the CHECK.
        if fallback.generator_name == "integer":
            bounds = self._check_range_bounds(col_name, check_constraints)
            if bounds is not None:
                cmin, cmax = bounds
                params = dict(fallback.params)
                if cmin is not None:
                    params["min_value"] = max(params.get("min_value", 0), cmin)
                if cmax is not None:
                    params["max_value"] = min(params.get("max_value", 999999), cmax)
                fallback = GeneratorSpec(
                    generator_name=fallback.generator_name,
                    params=params,
                    null_ratio=fallback.null_ratio,
                    provider=fallback.provider,
                )
        specs[col_name] = fallback
        # Recurse so string/integer fallbacks also get value-space expansion.
        return self.adjust(specs, {col_name}, count, column_infos, check_constraints)

    def _adjust_string(
        self,
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        _column_infos: list[ColumnInfo] | None,
    ) -> GeneratorSpec:
        """Adjust string column parameters: compute the required minimum length based on
        charset size to satisfy uniqueness.
        """
        params = dict(spec.params)
        params.setdefault("max_length", 50)
        params.setdefault("min_length", 1)
        max_length = params["max_length"]

        charset_size = 62
        if params.get("charset") == "digits":
            charset_size = 10
        elif params.get("charset") == "alpha":
            charset_size = 52

        min_needed = max(1, math.ceil(math.log(max(count * count * 50, 1)) / math.log(charset_size)))
        current_min = params["min_length"]
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
        check_constraints: list[Any] | None,
    ) -> GeneratorSpec:
        """Adjust integer column parameters: extend the value range to accommodate the target row count.

        When the original value range is insufficient, extends max_value by count*10;
        logs a warning when exceeding the limit for small-range types like INT8/INT16.

        A CHECK-bounded range (e.g. ``CHECK (year >= 2000 AND year <= 2026)``) is
        never widened: expanding past the CHECK bound generates values that
        violate the constraint (IntegrityError at insert). The range is instead
        clamped to the CHECK bounds, and a warning is emitted when the bounded
        domain is too small to hold ``count`` distinct values.
        """
        params = dict(spec.params)
        min_val = params.get("min_value", 0)
        max_val = params.get("max_value", 999999)
        if max_val - min_val < count * 10:
            bounds = self._check_range_bounds(col_name, check_constraints)
            if bounds is not None:
                cmin, cmax = bounds
                if cmin is not None:
                    min_val = max(min_val, cmin)
                if cmax is not None:
                    max_val = min(max_val, cmax)
                span = (cmax - cmin + 1) if (cmin is not None and cmax is not None) else None
                if span is not None and count > span:
                    logger.warning(
                        "CHECK-bounded UNIQUE integer column cannot hold count=%d distinct "
                        "values in range [%s, %s]; uniqueness not guaranteed",
                        count,
                        cmin,
                        cmax,
                        column=col_name,
                    )
                params["min_value"] = min_val
                params["max_value"] = max_val
            else:
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

    @staticmethod
    def _check_range_bounds(
        col_name: str,
        check_constraints: list[Any] | None,
    ) -> tuple[int, int] | None:
        """Return the integer [min, max] bounds a CHECK range imposes on ``col_name``.

        Only deterministic single-column integer ranges are honored (via
        ``CheckConstraintParser``); cross-column / unparseable CHECKs return None.
        Multiple range CHECKs are intersected (tightest lower / upper bound wins).
        """
        if not check_constraints:
            return None
        from sqlseed.core.check_parser import CheckConstraintParser

        cmin: int | None = None
        cmax: int | None = None
        for chk in check_constraints:
            parsed = CheckConstraintParser.parse(col_name, chk.expression)
            if parsed is None or parsed.kind != "range":
                continue
            if parsed.min_value is not None and parsed.min_value == int(parsed.min_value):
                v = int(parsed.min_value)
                cmin = v if cmin is None else max(cmin, v)
            if parsed.max_value is not None and parsed.max_value == int(parsed.max_value):
                v = int(parsed.max_value)
                cmax = v if cmax is None else min(cmax, v)
        if cmin is None and cmax is None:
            return None
        return cmin, cmax

    def _adjust_choice(
        self,
        specs: dict[str, GeneratorSpec],
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        column_infos: list[ColumnInfo] | None,
        check_constraints: list[Any] | None,
    ) -> dict[str, GeneratorSpec]:
        """Adjust choice column: fall back to type inference and recursively adjust when choices are insufficient."""
        choices = spec.params.get("choices", [])
        if len(choices) < count:
            col_info = None
            if column_infos:
                col_info = next((c for c in column_infos if c.name == col_name), None)
            if col_info:
                fallback = self._mapper.map_column(col_info, force_type_infer=True)
                if fallback.generator_name not in {"skip", "choice"}:
                    specs[col_name] = GeneratorSpec(
                        generator_name=fallback.generator_name,
                        params=fallback.params,
                        null_ratio=spec.null_ratio,
                        provider=fallback.provider,
                    )
                    specs = self.adjust(specs, {col_name}, count, column_infos, check_constraints)
        return specs
