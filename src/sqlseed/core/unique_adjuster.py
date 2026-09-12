"""Uniqueness adjuster: handles retry logic for unique constraint conflicts.

Adjusts generation parameters for string/integer/choice type columns before data generation:
ensures their value space is sufficient to accommodate the target row count: reducing
the probability of unique constraint conflicts.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed.generators._protocol import ConfigurationError
from sqlseed.generators._string_helpers import resolve_charset

if TYPE_CHECKING:
    from sqlseed.core.mapper import ColumnMapper, GeneratorSpec
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
        if count == 0:
            return specs
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
                specs[col_name] = self._adjust_string(spec, col_name, count, column_infos, check_constraints)
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
        if (col_info := next((c for c in (column_infos or []) if c.name == col_name), None)) is None:
            return specs
        if col_info.is_primary_key or col_info.default is not None or not col_info.nullable:
            return specs
        fallback = self._mapper.map_column(col_info, force_type_infer=True)
        if fallback.generator_name in {"skip", "autoincrement"}:
            return specs
        specs[col_name] = self._bound_integer_fallback(fallback, col_name, count, check_constraints)
        # Recurse so string/integer fallbacks also get value-space expansion.
        return self.adjust(specs, {col_name}, count, column_infos, check_constraints)

    def _bound_integer_fallback(
        self,
        fallback: GeneratorSpec,
        col_name: str,
        count: int,
        check_constraints: list[Any] | None,
    ) -> GeneratorSpec:
        """Choose a CHECK-valid domain for inferred defaults, not user ranges."""
        if fallback.generator_name != "integer":
            return fallback
        if (bounds := self._check_range_bounds(col_name, check_constraints)) is None:
            return fallback
        cmin, cmax = bounds
        params = dict(fallback.params)
        min_val, max_val = self._integer_bounds(params)
        # The type mapper's [0, 999999] is a sample domain, not a constraint.
        # Replace each known endpoint; on a one-sided CHECK, move the free
        # endpoint far enough into the allowed domain for UNIQUE sampling.
        if cmin is not None:
            params["min_value"] = cmin
        elif cmax is not None:
            params["min_value"] = min(min_val, cmax - count * 10)
        if cmax is not None:
            params["max_value"] = cmax
        elif cmin is not None:
            params["max_value"] = max(max_val, cmin + count * 10)
        return replace(fallback, params=params)

    def _adjust_string(
        self,
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        column_infos: list[ColumnInfo] | None,
        check_constraints: list[Any] | None,
    ) -> GeneratorSpec:
        """Adjust string column parameters: compute the required minimum length based on
        charset size to satisfy uniqueness. CHAR/VARCHAR and deterministic length
        CHECK bounds remain authoritative over probabilistic sampling headroom.
        Bounded domains retain shorter lengths when the full interval is needed.
        """
        params = dict(spec.params)
        params.setdefault("max_length", 50)
        params.setdefault("min_length", 1)
        length_bounds = self._string_length_bounds(col_name, column_infos, check_constraints)
        self._constrain_string_lengths(params, col_name, length_bounds)
        max_length = params["max_length"]

        if (charset_size := len(set(resolve_charset(params.get("charset"))))) < 2:
            min_length = params["min_length"]
            capacity = max_length - min_length + 1 if charset_size == 1 else int(min_length == max_length == 0)
            if spec.null_ratio == 0 and count > capacity:
                raise ConfigurationError(
                    f"Column '{col_name}': {charset_size}-character domain cannot provide {count} UNIQUE strings "
                    f"within lengths [{min_length}, {max_length}]."
                )
            return replace(spec, params=params)

        target_capacity = count * count * 50
        min_needed = math.ceil(math.log(target_capacity) / math.log(charset_size))
        current_min = params["min_length"]
        if length_bounds is not None and length_bounds[1] is not None:
            # The full interval matters: binary strings of lengths 1..2 have
            # six values, not just the four values of the longest length.
            # A power at least 2**count.bit_length() already exceeds count;
            # cap the exponent so a huge declared width never builds a huge integer.
            longest_capacity = charset_size ** min(max_length, count.bit_length())
            if count <= longest_capacity:
                params["min_length"] = min(max_length, max(current_min, min_needed))
            else:
                capacity = (longest_capacity * charset_size - charset_size**current_min) // (charset_size - 1)
                if spec.null_ratio == 0 and count > capacity:
                    raise ConfigurationError(
                        f"Column '{col_name}': lengths [{current_min}, {max_length}] cannot fit {count} UNIQUE strings."
                    )
            return replace(spec, params=params)
        params["min_length"] = max(current_min, min_needed)

        if params["min_length"] > max_length:
            if params.get("charset") is None:
                params["charset"] = "alphanumeric"
                charset_size = len(set(resolve_charset(params["charset"])))
                min_needed = math.ceil(math.log(target_capacity) / math.log(charset_size))
                params["min_length"] = max(current_min, min_needed)
            logger.debug(
                "Expanded string length from %d to %d for UNIQUE sampling with count=%d",
                max_length,
                params["min_length"],
                count,
                column=col_name,
            )
            params["max_length"] = params["min_length"]

        return replace(spec, params=params)

    @staticmethod
    def _constrain_string_lengths(
        params: dict[str, Any], col_name: str, length_bounds: tuple[int | None, int | None] | None
    ) -> None:
        """Intersect user string lengths with schema bounds before checking capacity."""
        if length_bounds is not None:
            cmin, cmax = length_bounds
            if cmin is not None:
                params["min_length"] = max(params["min_length"], cmin)
            if cmax is not None:
                params["max_length"] = min(params["max_length"], cmax)
            if params["min_length"] > params["max_length"]:
                raise ConfigurationError(
                    f"Column '{col_name}': string length domain has no intersection with schema bounds."
                )

    @staticmethod
    def _string_length_bounds(
        col_name: str,
        column_infos: list[ColumnInfo] | None,
        check_constraints: list[Any] | None,
    ) -> tuple[int | None, int | None] | None:
        """Intersect declared CHAR/VARCHAR lengths and deterministic length CHECKs."""
        from sqlseed.core.check_parser import CheckConstraintParser

        lower_bounds: list[int] = []
        upper_bounds: list[int] = []
        for column in column_infos or []:
            if (
                column.name == col_name
                and (match := re.fullmatch(r"(?:VAR)?CHAR\((\d+)\)", column.type.upper())) is not None
            ):
                upper_bounds.append(int(match[1]))
        for check in check_constraints or []:
            parsed = CheckConstraintParser.parse(col_name, check.expression)
            if parsed is None or parsed.kind != "length_range":
                continue
            if parsed.min_length is not None:
                lower_bounds.append(parsed.min_length)
            if parsed.max_length is not None:
                upper_bounds.append(parsed.max_length)
        if not lower_bounds and not upper_bounds:
            return None
        return max(lower_bounds, default=None), min(upper_bounds, default=None)

    def _adjust_integer(
        self,
        spec: GeneratorSpec,
        col_name: str,
        count: int,
        _column_infos: list[ColumnInfo] | None,
        check_constraints: list[Any] | None,
    ) -> GeneratorSpec:
        """Adjust integer column parameters: extend the value range to accommodate the target row count.

        When the original value range is insufficient, extends max_value by count*10.
        Type names alone are not capacity bounds: SQLite does not enforce integer
        widths, and PostgreSQL INT8 denotes an eight-byte integer, not eight bits.

        A CHECK-bounded range (e.g. ``CHECK (year >= 2000 AND year <= 2026)``) is
        never widened: expanding past the CHECK bound generates values that
        violate the constraint (IntegrityError at insert). The range is instead
        clamped to the CHECK bounds. A non-null domain that cannot hold ``count``
        distinct values is rejected before generation; nullable UNIQUE values
        can exceed the non-null capacity because NULL may repeat.
        """
        params = dict(spec.params)
        min_val, max_val = self._integer_bounds(params)
        if (bounds := self._check_range_bounds(col_name, check_constraints)) is not None:
            cmin, cmax = bounds
            if cmin is not None:
                min_val = max(min_val, cmin)
            if cmax is not None:
                max_val = min(max_val, cmax)
            if spec.null_ratio == 0 and count > max_val - min_val + 1:
                raise ConfigurationError(
                    f"Column '{col_name}': integer range [{min_val}, {max_val}] cannot provide {count} UNIQUE values."
                )
        else:
            max_val = max(max_val, min_val + count * 10)
        params["min_value"] = min_val
        params["max_value"] = max_val
        return replace(spec, params=params)

    @staticmethod
    def _integer_bounds(params: dict[str, Any]) -> tuple[int, int]:
        """Share provider defaults between inferred and explicit integer domains."""
        return params.get("min_value", 0), params.get("max_value", 999999)

    @staticmethod
    def _check_range_bounds(
        col_name: str,
        check_constraints: list[Any] | None,
    ) -> tuple[int | None, int | None] | None:
        """Return the integer [min, max] bounds a CHECK range imposes on ``col_name``.

        Only deterministic single-column integer ranges are honored (via
        ``CheckConstraintParser``); cross-column / unparseable CHECKs return None.
        Multiple range CHECKs are intersected (tightest lower / upper bound wins).
        Either bound may be ``None`` when only a one-sided range is present.
        """
        if not check_constraints:
            return None
        from sqlseed.core.check_parser import CheckConstraintParser

        lower_bounds: list[int] = []
        upper_bounds: list[int] = []
        for chk in check_constraints:
            parsed = CheckConstraintParser.parse(col_name, chk.expression)
            if parsed is None or parsed.kind != "range":
                continue
            if parsed.min_value is not None:
                v = math.floor(parsed.min_value) + 1 if parsed.min_exclusive else math.ceil(parsed.min_value)
                lower_bounds.append(v)
            if parsed.max_value is not None:
                v = math.ceil(parsed.max_value) - 1 if parsed.max_exclusive else math.floor(parsed.max_value)
                upper_bounds.append(v)
        cmin = max(lower_bounds, default=None)
        cmax = min(upper_bounds, default=None)
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
        if len(choices) < count and (col_info := next((c for c in (column_infos or []) if c.name == col_name), None)):
            fallback = self._mapper.map_column(col_info, force_type_infer=True)
            if fallback.generator_name not in {"skip", "choice"}:
                fallback = self._bound_integer_fallback(fallback, col_name, count, check_constraints)
                specs[col_name] = replace(
                    spec,
                    generator_name=fallback.generator_name,
                    params=fallback.params,
                    provider=fallback.provider,
                )
                specs = self.adjust(specs, {col_name}, count, column_infos, check_constraints)
        return specs
