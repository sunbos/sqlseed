"""Ordered cross-column CHECK matchers and deterministic expression builders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlseed_ai.auto_heal._check_inference import (
    _has_like_constraint,
    _infer_from_check_constraints,
    _is_date_column,
    _is_date_only_type,
    _is_datetime_type,
    _normalize_constraints,
    _placeholder_generator,
    _range_expr_for_op,
)

_SINGLE_QUOTED_VALUE = "'([^']*)'"
_DOUBLE_QUOTED_VALUE = '"([^"]*)"'
_SQL_AND = " AND "
_INTEGER_ABOVE_SOURCE = "value + random_int(1, 100)"
_INTEGER_BELOW_SOURCE = "value - random_int(1, 100)"
_FLOAT_ABOVE_SOURCE = "value + random_float(0.01, 100.0)"
_INTEGER_AT_OR_ABOVE_SOURCE = "value + random_int(0, 100)"
_FLOAT_BELOW_SOURCE = "value - random_float(0.01, 100.0)"
_INTEGER_AT_OR_BELOW_SOURCE = "value - random_int(0, 100)"


def _infer_cross_column_config(
    col_name: str,
    constraints: list[dict[str, Any]],
    all_columns: list[str],
    col_type: str,
    fk_columns: set[str] | None = None,
    self_ref_fk_cols: set[str] | None = None,
    column_types: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Infer config from cross-column CHECK constraints.

    Returns a config dict with either:
    - ``derive_from`` + ``expression`` (for derived mode — date/numeric ordering)
    - ``generator`` + ``params`` + ``null_ratio`` (for source mode — always NULL)

    Or ``None`` if no inference is possible.

    The ``fk_columns`` parameter is a set of column names that are foreign
    keys. For FK columns, Pattern 30 returns ``None`` for BOTH branches
    (always NULL) because returning a literal like ``0`` causes FK
    violations (auto-increment IDs start from 1, so 0 is never valid).

    Handled patterns (where ``col`` is ``col_name`` and ``other`` is another column):
    - ``col IS NULL OR col (>=|>) other`` → derive_from other, add timedelta
    - ``col >= other`` (standalone) → derive_from other, add timedelta/offset
    - ``col > other`` (standalone) → derive_from other, multiply by factor > 1
    - ``col <= other`` (standalone) → derive_from other, multiply by factor <= 1
    - ``col < other`` (standalone) → derive_from other, multiply by factor < 1
    - ``col IS NULL OR col = expr`` → null_ratio=1.0 (computed columns)
    - ``col IS NULL OR other = 'value'`` → null_ratio=1.0 (conditional NULL)
    - ``col != other`` (integer inequality — safe ternary offset)
    - ``col >= col1 * col2`` (arithmetic — derive_from col1, reference col2)
    - ``col = col1 (+|-|*) col2`` (arithmetic equality — derive_from col1, reference col2)
    - ``col = col1 + col2 + col3`` (three-column addition — derive_from col1, reference col2 + col3)
    - ``col = abs(col1) (+|-|*) col2`` (abs first operand — derive_from col1, expression uses abs(value))
    - ``col = col1 (+|-|*) abs(col2)`` (abs second operand — derive_from col1, expression uses abs(row[col2]))
    - ``col = abs(col1) * abs(col2)`` (abs both operands — derive_from col1, expression uses abs() on both)
    - ``col = abs(col1)`` (standalone abs — derive_from col1, expression abs(value))
    - ``col >= X AND col <= other`` (compound — literal lower + column upper)
    - ``col >= other AND col <= Y`` (compound — column lower + literal upper)
    - ``col > X AND col < other`` (compound — exclusive literal lower + exclusive column upper)
    - ``col > other AND col < Y`` (compound — exclusive column lower + exclusive literal upper)
    - ``col != VALUE OR other_col = VALUE2`` (conditional equality — derive col from other_col)
    - ``col1 + col2 = col`` (reverse sum equality — derive addend from total)
    - ``col = VALUE OR other_col < col2 OR other_col > col3`` (range membership — derive col from other_col's range)
    - ``col = (col1 + col2 [+ col3]) / N`` (average of N columns — derive from col1, reference others)
    - ``col <= col2 * CONSTANT`` (percentage/scalar upper bound — derive from col2)

    Skipped patterns (not safely inferable from CHECK alone):
    - ``col != other`` for non-integer columns (needs FK pool awareness)
    """
    # Normalize constraints (strip PG ::type casts and outer parens) so
    # regex patterns can match PostgreSQL-normalized CHECK expressions.
    constraints = _normalize_constraints(constraints)
    col = re.escape(col_name)
    col_set = set(all_columns)
    is_date_type = any(k in col_type.upper() for k in ("DATE", "TIME", "DATETIME"))
    # SQLite stores dates as TEXT, so also check column name patterns.
    is_date_col = is_date_type or _is_date_column(col_name)
    # Formatted string columns (with LIKE constraints, e.g., ``start_time LIKE
    # '__:__'``) are NOT real datetimes or numbers — they store formatted
    # strings like "HH:MM". ANY ``derive_from`` expression that does
    # arithmetic on such a column's value (``value + ...``, ``value * ...``,
    # ``timedelta(...)``) fails at fill time with ``TypeError: can only
    # concatenate str (not X) to str``. Return None immediately so the
    # single-column inference path (which handles LIKE → ``pattern``
    # generator) takes precedence over cross-column derive_from.
    if _has_like_constraint(col_name, constraints):
        return None
    is_float_type = any(k in col_type.upper() for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC"))
    is_int_type = any(k in col_type.upper() for k in ("INT", "BIGINT", "SMALLINT", "TINYINT"))
    # FK columns: returning a literal (e.g., 0) for FK columns causes FK
    # violations because auto-increment IDs start from 1. For nullable FK
    # columns, None (NULL) is always valid. For NOT NULL FK columns, the
    # derive_from approach is insufficient — the LLM or BrokenEdgeAligner
    # must handle FK pool assignment. Here we detect FK columns so Pattern 30
    # can return None for both branches (always NULL).
    is_fk_column = fk_columns is not None and col_name in fk_columns

    context = _CrossColumnContext(
        col_name=col_name,
        col_type=col_type,
        constraints=constraints,
        all_columns=all_columns,
        col=col,
        col_set=col_set,
        is_date_col=is_date_col,
        is_float_type=is_float_type,
        is_int_type=is_int_type,
        is_fk_column=is_fk_column,
        column_types=column_types,
        self_ref_fk_cols=self_ref_fk_cols,
    )
    for infer in (
        _infer_dual_multiplier_bounds,
        _infer_self_reference_condition,
        _infer_nullable_three_way_comparison,
        _infer_conditional_null_with_sibling,
        _infer_conditional_range_priority,
    ):
        if (inferred := infer(context)) is not None:
            return inferred

    for constraint in sorted(constraints, key=_cross_constraint_sort_key):
        if (inferred := _infer_cross_column_check(context, constraint)) is not None:
            return inferred
    return None


@dataclass(frozen=True)
class _CrossColumnContext:
    """Normalized schema inputs shared by ordered CHECK matchers."""

    col_name: str
    col_type: str
    constraints: list[dict[str, Any]]
    all_columns: list[str]
    col: str
    col_set: set[str]
    is_date_col: bool
    is_float_type: bool
    is_int_type: bool
    is_fk_column: bool
    column_types: dict[str, str] | None
    self_ref_fk_cols: set[str] | None


def _cross_constraint_sort_key(c: dict[str, Any]) -> tuple[int, int]:
    if c.get("type") != "check":
        return (2, 0)
    expr = c.get("expression", "")
    # Conditional constraints (with OR) get priority 0
    if re.search(r"(?<=\s)OR(?=\s)", expr, re.IGNORECASE):
        # Secondary: constraints with ``IN (...)`` are more restrictive
        # (they force a specific NULL/value for non-matching cases)
        if re.search(r"\bIN\s*\(", expr, re.IGNORECASE):
            return (0, 0)
        return (0, 1)
    # Compound range constraints (with AND) get priority 1
    return (1, 0)


def _infer_cross_column_check(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col = context.col
    col_name = context.col_name
    all_columns = context.all_columns
    constraints = context.constraints
    if c.get("type") != "check":
        return None
    if not (expr := c.get("expression", "")):
        return None
    # Check if col_name appears in the expression
    if not re.search(rf"\b{col}\b", expr, re.IGNORECASE):
        return None
    # Check if any other column appears (cross-column)
    other_cols_in_expr = [
        other
        for other in all_columns
        if other != col_name and re.search(rf"\b{re.escape(other)}\b", expr, re.IGNORECASE)
    ]
    if not other_cols_in_expr:
        return None  # Single-column constraint, handled by _infer_from_check_constraints
    # Skip constraints where any other column has a LIKE constraint —
    # arithmetic on a formatted string (e.g., ``start_time`` storing
    # "HH:MM") fails at fill time. The column should use a ``pattern``
    # generator (from single-column LIKE inference) instead of a
    # ``derive_from`` that does arithmetic on the string value.
    if any(_has_like_constraint(oc, constraints) for oc in other_cols_in_expr):
        return None

    for match in (
        _match_nullable_computed,
        _match_conditional_null,
        _match_nullable_three_way,
        _match_nullable_ordering,
        _match_date_left_ordering,
        _match_nullable_sum_upper,
        _match_sum_upper,
        _match_date_right_ordering,
        _match_inclusive_lower,
        _match_exclusive_lower,
        _match_inclusive_upper,
        _match_literal_lower_column_upper,
        _match_column_lower_literal_upper,
        _match_exclusive_literal_lower_column_upper,
        _match_exclusive_column_lower_literal_upper,
        _match_inclusive_literal_lower_exclusive_column_upper,
        _match_exclusive_upper,
        _match_column_inequality,
        _match_conditional_integer_equality,
        _match_product_lower,
        _match_product_equality,
        _match_multiplier_lower,
        _match_binary_arithmetic,
        _match_sum_equality,
        _match_absolute_difference,
        _match_affine_upper,
        _match_product_quotient,
        _match_principal_plus_product,
        _match_reverse_sum,
        _match_range_indicator,
        _match_average,
        _match_multiplier_upper,
        _match_threshold_indicator,
        _match_literal_or_comparison,
        _match_conditional_comparison,
        _match_product_with_offset,
        _match_discounted_sum,
        _match_literal_or_enum,
        _match_conditional_enum,
        _match_conditional_enum_equalities,
        _match_conditional_dual_ranges,
        _match_conditional_ranges,
        _match_conditional_string_mapping,
        _match_conditional_numeric_mapping,
        _match_disjunction_indicator,
        _match_conditional_positive,
        _match_absolute_left_arithmetic,
        _match_absolute_right_arithmetic,
        _match_absolute_product,
        _match_absolute_value,
        _match_three_operand_arithmetic,
        _match_conditional_null_value,
        _match_conditional_nonnull,
        _match_conditional_integer_nonnull,
        _match_conditional_not_in_nonnull,
        _match_conditional_numeric_equality,
        _match_bounded_multiplier,
        _match_conditional_positive_or_null,
        _match_conditional_arithmetic,
        _match_conditional_upper,
        _match_conditional_integer_upper,
        _match_conditional_integer_positive,
        _match_literal_or_threshold,
        _match_enum_or_null,
    ):
        if (inferred := match(context, c)) is not None:
            return inferred
    return None


def _infer_dual_multiplier_bounds(context: _CrossColumnContext) -> dict[str, Any] | None:
    col_name = context.col_name
    constraints = context.constraints
    col = context.col
    col_set = context.col_set
    # Pattern 22c: col >= col2 * CONST1 AND col <= col2 * CONST2 (dual multiplier
    # bounds — two separate CHECK constraints that together define a range
    # as a multiple of col2). This must be checked BEFORE the per-constraint
    # loop because Pattern 7b would match the lower bound alone and return
    # ``value * CONST1`` (a fixed multiplier), ignoring the upper bound.
    # e.g., base_price_yearly >= base_price_monthly * 10
    #       base_price_yearly <= base_price_monthly * 12
    # Derive from col2, multiply by random_float(CONST1, CONST2).
    lower_mult: float | None = None
    upper_mult: float | None = None
    mult_src_col: str | None = None
    for c in constraints:
        if c.get("type") != "check":
            continue
        expr_c = c.get("expression", "")
        # Lower bound: col >= col2 * CONST1
        m_low = re.match(
            rf"^\s*{col}\s*>=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
            expr_c,
            re.IGNORECASE,
        )
        if m_low and m_low.group(1) in col_set and m_low.group(1) != col_name:
            lower_mult = float(m_low.group(2))
            mult_src_col = m_low.group(1)
        # Upper bound: col <= col2 * CONST2
        m_up = re.match(
            rf"^\s*{col}\s*<=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
            expr_c,
            re.IGNORECASE,
        )
        if m_up and m_up.group(1) in col_set and m_up.group(1) != col_name:
            upper_mult = float(m_up.group(2))
            if mult_src_col is None:
                mult_src_col = m_up.group(1)
            elif mult_src_col != m_up.group(1):
                # Different source columns — not a dual-bound pattern
                upper_mult = None
    if lower_mult is not None and upper_mult is not None and mult_src_col is not None and lower_mult <= upper_mult:
        return {
            "derive_from": mult_src_col,
            "expression": f"value * random_float({lower_mult}, {upper_mult})",
        }

    # Pattern 40: self-ref FK conditional equality — when col2 is a self-ref
    return None


def _infer_self_reference_condition(context: _CrossColumnContext) -> dict[str, Any] | None:
    col_name = context.col_name
    constraints = context.constraints
    col = context.col
    # FK (always NULL at fill time) and constraint is
    # ``col1 = VALUE OR col2 IS NOT NULL``, col1 must be VALUE.
    # Since col2 is always NULL, ``col2 IS NOT NULL`` is always FALSE, so
    # ``col1 = VALUE`` must be TRUE. Force col1 to a choice with only VALUE.
    # This must be a PRE-LOOP scan because it applies to col1 (not col2), and
    # the per-constraint loop might match a less restrictive pattern first.
    # e.g., org_type = 'root' OR parent_id IS NOT NULL (parent_id is self-ref FK)
    if not (self_ref_fk_cols := context.self_ref_fk_cols):
        return None
    for c in constraints:
        if c.get("type") != "check":
            continue
        if inferred := _match_self_reference_literal(col_name, col, self_ref_fk_cols, c.get("expression", "")):
            return inferred
    return None


def _match_self_reference_literal(
    col_name: str, col: str, self_ref_fk_cols: set[str], expr_p40: str
) -> dict[str, Any] | None:
    m_p40 = re.match(
        rf"^\s*{col}\s*=\s*'([^']+)'\s+OR\s+(\w+)\s+IS\s+NOT\s+NULL\s*$",
        expr_p40,
        re.IGNORECASE,
    )
    if m_p40:
        val_p40 = m_p40.group(1)
        other_col_p40 = m_p40.group(2)
        if other_col_p40 in self_ref_fk_cols and other_col_p40 != col_name:
            return {
                "generator": "choice",
                "params": {"choices": [val_p40]},
            }
    # Pattern 40 (int variant): col = INT_VALUE OR other_col IS NOT NULL
    # e.g., level = 1 OR parent_id IS NOT NULL (parent_id is self-ref FK)
    # Same semantics as the string variant but with an unquoted integer.
    m_p40_int = re.match(
        rf"^\s*{col}\s*=\s*(\d+)\s+OR\s+(\w+)\s+IS\s+NOT\s+NULL\s*$",
        expr_p40,
        re.IGNORECASE,
    )
    if m_p40_int:
        val_p40_int = int(m_p40_int.group(1))
        other_col_p40_int = m_p40_int.group(2)
        if other_col_p40_int in self_ref_fk_cols and other_col_p40_int != col_name:
            return {
                "generator": "choice",
                "params": {"choices": [val_p40_int]},
            }
    return None


def _infer_nullable_three_way_comparison(context: _CrossColumnContext) -> dict[str, Any] | None:
    constraints = context.constraints
    # Pattern 1b pre-loop scan: 3-way OR constraints must be checked BEFORE
    # the per-constraint loop. Without this, a Pattern 1 (2-way OR) constraint
    # on the same column would match first and return early, preventing
    # Pattern 1b from ever being evaluated.
    # e.g., api_keys.revoked_at has both:
    #   - revoked_at IS NULL OR revoked_at >= created_at  (Pattern 1, 2-way)
    #   - revoked_at IS NULL OR expires_at IS NULL OR revoked_at <= expires_at  (Pattern 1b, 3-way)
    # Pattern 1b is more restrictive (involves 2 other columns), so it wins.
    #
    # Lower bound awareness: when the upper-bound branch (<= or <) is taken,
    # scan all constraints for a sibling lower-bound pattern
    # ``col IS NULL OR col (>=|>) other_col2``. If found, the subtracted /
    # decremented expression may produce a value below the lower bound
    # (e.g., revoked_at derived from expires_at minus up to 365 days can
    # land before created_at). Wrap with ``max(result, row['other_col2'])``
    # so the value respects both bounds simultaneously. ``max`` is in
    # SAFE_FUNCTIONS (see core/expression.py). This is only applied to the
    # upper-bound branch; the lower-bound branch (>=, >) adds to ``value``
    # and therefore cannot violate a sibling upper bound that Pattern 1b
    # already enforces via the derive_from source column.
    lower_bound_col_p1b = _find_nullable_lower_column(context)
    # Literal bound awareness: scan for literal numeric bounds on this column.
    # ``col IS NULL OR col (>=|>) X`` (X is a number) → lower bound literal
    # ``col IS NULL OR col (<=|<) Y`` (Y is a number) → upper bound literal
    # When the Pattern 1b branch expression could violate a literal bound,
    # wrap with ``max(result, X)`` / ``min(result, Y)`` to enforce both.
    # e.g., R3.warehouses.temperature_max has:
    #   - temperature_max IS NULL OR temperature_max <= 40.0  (literal upper)
    #   - Pattern 1b: temperature_max > temperature_min → value * 1.01-2.0
    # Without min() wrapping, value * 2.0 can exceed 40.0.
    lower_bound_literal_p1b, upper_bound_literal_p1b = _find_nullable_literal_bounds(context)
    bounds = _NullableComparisonBounds(lower_bound_col_p1b, lower_bound_literal_p1b, upper_bound_literal_p1b)
    for c in constraints:
        if (inferred := _match_bounded_nullable_three_way(context, c, bounds)) is not None:
            return inferred
    return None


def _infer_conditional_null_with_sibling(context: _CrossColumnContext) -> dict[str, Any] | None:
    is_date_col = context.is_date_col
    is_float_type = context.is_float_type
    # Pattern 30 pre-loop scan: ``col1 != VALUE OR col IS NULL`` must be
    # checked BEFORE the per-constraint loop. Without this, a Pattern 1
    # constraint (``col IS NULL OR col >= other_col``) on the same column
    # would match first and return early, preventing Pattern 30 from ever
    # being evaluated.
    # e.g., R2.prescriptions.dispensed_at has both:
    #   - status != 'cancelled' OR dispensed_at IS NULL  (Pattern 30)
    #   - dispensed_at IS NULL OR dispensed_at >= prescribed_at  (Pattern 1)
    # Pattern 1 would make dispensed_at always non-NULL, violating Pattern 30
    # when status == 'cancelled'.
    #
    # Sibling Pattern 1 awareness: when both Pattern 30 and Pattern 1 exist,
    # derive from Pattern 1's source column (other_col) with a conditional
    # NULL: ``None if row['col1'] == 'VALUE' else (value + timedelta(...))``.
    # This satisfies BOTH constraints simultaneously:
    #   - Pattern 30: when col1 == VALUE, col is None ✓
    #   - Pattern 1: when col is not None, col >= other_col ✓
    # The ``row['col1']`` access is supported by the expression engine.
    #
    # Datetime fix: without a sibling Pattern 1, datetime columns return
    # None for BOTH branches (not 0, which is invalid for datetime). The
    # per-constraint Pattern 30 code handles FK and non-datetime non-FK
    # columns.
    p30_other_col, p30_val_str, p30_sibling_col = _find_conditional_null_sibling(context)
    if p30_other_col is not None and p30_val_str is not None:
        # Case 1: Pattern 30 + sibling Pattern 1 → cross-column derive
        if p30_sibling_col is not None:
            if is_date_col or _is_date_column(p30_sibling_col):
                return {
                    "derive_from": p30_sibling_col,
                    "expression": (
                        f"None if row['{p30_other_col}'] == '{p30_val_str}' else "
                        f"(None if value is None else value + timedelta(days=random_int(1, 365)))"
                    ),
                }
            if is_float_type:
                return {
                    "derive_from": p30_sibling_col,
                    "expression": (
                        f"None if row['{p30_other_col}'] == '{p30_val_str}' else "
                        f"(None if value is None else value + random_float(0, 100))"
                    ),
                }
            return {
                "derive_from": p30_sibling_col,
                "expression": (
                    f"None if row['{p30_other_col}'] == '{p30_val_str}' else "
                    f"(None if value is None else value + random_int(0, 100))"
                ),
            }
        # Case 2: Pattern 30 + datetime column (no sibling Pattern 1) → always None
        # 0 is not a valid datetime value; None (NULL) is always safe.
        if is_date_col:
            return {
                "derive_from": p30_other_col,
                "expression": f"None if value == '{p30_val_str}' else None",
            }
    return None


def _infer_conditional_range_priority(context: _CrossColumnContext) -> dict[str, Any] | None:
    col_name = context.col_name
    constraints = context.constraints
    col = context.col
    col_set = context.col_set
    # Pattern 27 pre-loop scan: N-way conditional range must be checked BEFORE
    # the per-constraint loop. Without this, a Pattern 18 constraint
    # (``other_col != 'VALUE' OR col = X``) on the same column would match
    # first and return early, preventing Pattern 27 from ever being evaluated.
    # e.g., R5.enrollments.progress_percent has both:
    #   - status != 'completed' OR progress_percent = 100  (Pattern 18)
    #   - status = 'active' AND progress_percent >= 0 OR status = 'completed'
    #     AND progress_percent >= 100 OR status = 'dropped' AND progress_percent < 100
    #     (Pattern 27, multi-clause)
    # Pattern 27 is more specific (per-status ranges), so it wins.
    # Guard: skip if the constraint has dual bounds per clause (Pattern 36).
    # Pattern 36 clauses look like ``col >= X AND col < Y`` (two comparisons
    # on col per clause). If the number of ``col OP`` occurrences is more than
    # the number of enum assignments, it's Pattern 36, not Pattern 27.
    for c_p27_pre in constraints:
        if c_p27_pre.get("type") != "check":
            continue
        expr_p27_pre = c_p27_pre.get("expression", "")
        if " OR " not in expr_p27_pre or _SQL_AND not in expr_p27_pre:
            continue
        if not re.search(rf"\b{col}\b", expr_p27_pre, re.IGNORECASE):
            continue
        clause_re_p27_pre = (
            rf"(\w+)\s*=\s*'([^']+)'\s+AND\s+{col}\s*"
            r"(>=|<=|>|<)\s*(-?[0-9]+(?:\.[0-9]+)?)"
        )
        clauses_p27_pre = re.findall(clause_re_p27_pre, expr_p27_pre)
        if len(clauses_p27_pre) < 2:
            continue
        other_col_p27_pre = clauses_p27_pre[0][0]
        if (
            other_col_p27_pre not in col_set
            or other_col_p27_pre == col_name
            or not all(cl[0] == other_col_p27_pre for cl in clauses_p27_pre)
        ):
            continue
        # Guard: count enum assignments vs col comparisons. If
        # comparisons > assignments, it's Pattern 36 (dual bounds).
        enum_count = len(re.findall(rf"{other_col_p27_pre}\s*=\s*'[^']+'", expr_p27_pre, re.IGNORECASE))
        if len(re.findall(rf"\b{col}\s*(>=|<=|>|<)\s*", expr_p27_pre, re.IGNORECASE)) > enum_count:
            continue  # Pattern 36 — skip, let per-loop Pattern 36 handle it
        return _build_conditional_priority_range(context, other_col_p27_pre, clauses_p27_pre)
    return None


def _match_nullable_computed(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col_type = context.col_type
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 4: col IS NULL OR col = expr (computed column with NULL escape)
    # e.g., line_total IS NULL OR line_total = quantity * unit_price * (1 - discount)
    # IMPORTANT: the negative lookbehind ``(?<![<>])`` ensures ``=`` is not
    # part of ``<=`` or ``>=``. Without this, the regex would match
    # ``col IS NULL OR col <= expr`` (a comparison, not an equality),
    # incorrectly returning null_ratio=1.0. This caused R7
    # claims.approved_amount to be all-NULL because Pattern 4 matched
    # ``approved_amount IS NULL OR approved_amount <= claim_amount``
    # before Pattern 30b NOT IN could match
    # ``status NOT IN ('approved','settled') OR approved_amount IS NOT NULL``.
    #
    # Pattern 4a: when the expression after ``=`` is a simple 2-column
    # multiplication (``col = col1 * col2``), convert to derive_from
    # instead of returning null_ratio=1.0. This produces realistic
    # business data (e.g., line_total = unit_price * quantity) instead
    # of all-NULLs. Uses null_ratio=0.3 so 30% of values are NULL
    # (satisfying the IS NULL branch) and 70% are computed (satisfying
    # the equality branch).
    m_p4_mul = re.search(
        rf"{col}\s+IS\s+NULL\s+OR\s+{col}\s*(?<![<>])=\s*(\w+)\s*\*\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m_p4_mul:
        col1_p4, col2_p4 = m_p4_mul.group(1), m_p4_mul.group(2)
        if col1_p4 in col_set and col2_p4 in col_set and col1_p4 != col_name:
            return {
                "derive_from": col1_p4,
                "expression": f"value * row['{col2_p4}']",
                "null_ratio": 0.3,
            }

    if re.search(rf"{col}\s+IS\s+NULL\s+OR\s+{col}\s*(?<![<>])=", expr, re.IGNORECASE):
        return {
            "generator": _placeholder_generator(col_type),
            "params": {},
            "null_ratio": 1.0,
        }
    return None


def _match_conditional_null(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_type = context.col_type
    col = context.col
    expr = c.get("expression", "")
    # Pattern 5: col IS NULL OR other_col = 'value' (conditional NULL)
    # e.g., completed_at IS NULL OR status = 'completed'
    m = re.search(
        rf"{col}\s+IS\s+NULL\s+OR\s+(\w+)\s*=\s*'([^']*)'",
        expr,
        re.IGNORECASE,
    )
    if m:
        return {
            "generator": _placeholder_generator(col_type),
            "params": {},
            "null_ratio": 1.0,
        }
    return None


def _match_nullable_three_way(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 1b: 3-way OR — col IS NULL OR other IS NULL OR col (>=|>|<=|<) other
    # This is Pattern 1 extended with an ``other_col IS NULL`` escape clause.
    # When other_col is NULL, col can be anything (including NULL). The
    # expression must guard against ``value is None`` to avoid TypeError
    # when subtracting timedelta or multiplying None.
    # e.g., revoked_at IS NULL OR expires_at IS NULL OR revoked_at <= expires_at
    # Also handles reversed ordering: other IS NULL OR col IS NULL OR col OP other
    # e.g., temperature_min IS NULL OR temperature_max IS NULL OR temperature_max > temperature_min
    m = re.search(
        rf"{col}\s+IS\s+NULL\s+OR\s+(\w+)\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
        expr,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(
            rf"(\w+)\s+IS\s+NULL\s+OR\s+{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
            expr,
            re.IGNORECASE,
        )
    if m:
        other_col_p1b = m.group(1)
        op_p1b = m.group(2)
        other_col_ref_p1b = m.group(3)
        if other_col_p1b == other_col_ref_p1b and other_col_p1b in col_set and other_col_p1b != col_name:
            return _build_nullable_three_way(context, other_col_p1b, op_p1b)
    return None


def _match_nullable_ordering(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 1: col IS NULL OR col (>=|>|<=|<) other_col (ordering with NULL escape)
    # Also handles: col IS NULL OR other IS NULL OR col >= other
    # e.g., termination_date IS NULL OR termination_date >= hire_date
    # e.g., due_date IS NULL OR start_date IS NULL OR due_date >= start_date
    # e.g., assessment_price IS NULL OR assessment_price <= listing_price
    #
    # Single-column range-bound awareness: before applying Pattern 1,
    # scan all constraints for a single-column range CHECK on this column
    # (e.g., ``col IS NULL OR (col >= 40 AND col <= 150)``). When found,
    # the Pattern 1 expression (e.g., ``value - random_int(1, 100)``) is
    # wrapped with ``max(LOWER, min(UPPER, expr))`` to enforce both the
    # cross-column ordering AND the single-column range simultaneously.
    # Without this, ``value - random_int(1, 100)`` can produce values
    # outside [LOWER, UPPER] (e.g., high=60 → low=-40, violating >= 40).
    p1_lower, p1_upper = _find_nullable_ordering_bounds(context)
    # e.g., budget_max IS NULL OR budget_min IS NULL OR budget_max >= budget_min
    # All four comparison operators are handled. For dates, timedelta is
    # used; for floats, multiplication factors; for ints, additive offsets.
    m = re.search(
        rf"{col}\s+IS\s+NULL.*OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
        expr,
        re.IGNORECASE,
    )
    if m:
        op = m.group(1)
        other_col = m.group(2)
        if other_col in col_set and other_col != col_name:
            return _build_nullable_ordering(context, other_col, op, p1_lower, p1_upper)
    return None


def _match_date_left_ordering(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_date_col = context.is_date_col
    expr = c.get("expression", "")
    # Pattern 1 (DATE-on-left variant): col IS NULL OR DATE(col) OP other_col
    # e.g., paid_at IS NULL OR DATE(paid_at) >= due_date
    # Same semantics as Pattern 1 but with a DATE() wrapper on the left
    # column. When col is not NULL, DATE(col) must satisfy the comparison
    # with other_col. The expression generates col = other_col + positive
    # timedelta (for >=, >) or other_col - timedelta (for <=, <).
    m_date_left = re.search(
        rf"{col}\s+IS\s+NULL\s+OR\s+DATE\s*\(\s*{col}\s*\)\s*(>=|>|<=|<)\s*(\w+)",
        expr,
        re.IGNORECASE,
    )
    if m_date_left:
        op_dl = m_date_left.group(1)
        other_col_dl = m_date_left.group(2)
        if other_col_dl in col_set and other_col_dl != col_name and (is_date_col or _is_date_column(other_col_dl)):
            if op_dl in {">=", ">"}:
                return {
                    "derive_from": other_col_dl,
                    "expression": "value + timedelta(days=random_int(1, 365))",
                }
            days_dl = "0" if op_dl == "<=" else "1"
            return {
                "derive_from": other_col_dl,
                "expression": f"value - timedelta(days=random_int({days_dl}, 365))",
            }
    return None


def _match_nullable_sum_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 39: col1 IS NULL OR col <= col2 + col3 (compound addition upper bound)
    # e.g., quota_limit IS NULL OR metric_value <= quota_limit + overage_amount
    # Semantics: when col1 (quota_limit) is NULL, col can be anything;
    # otherwise col must be <= col2 + col3. Derive from col2 (quota_limit):
    # when value is None, return a safe random; otherwise return
    # (value + row['col3']) * random_factor to stay under the bound.
    m = re.match(
        rf"^\s*(\w+)\s+IS\s+NULL\s+OR\s+{col}\s*<=\s*(\w+)\s*\+\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col2_p39 = m.group(2)
        col3_p39 = m.group(3)
        if col2_p39 in col_set and col3_p39 in col_set and col_name not in (col2_p39, col3_p39):
            return {
                "derive_from": col2_p39,
                "expression": (f"None if value is None else (value + row['{col3_p39}']) * random_float(0.0, 1.0)"),
            }
    return None


def _match_sum_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 39 (no-NULL variant): col <= col2 + col3 (compound addition
    # upper bound without NULL escape).
    # e.g., available_balance <= balance + overdraft_limit
    # Same arithmetic as Pattern 39 but without the ``col1 IS NULL OR``
    # prefix — col must ALWAYS satisfy ``col <= col2 + col3``.
    m_nn_p39 = re.match(
        rf"^\s*{col}\s*<=\s*(\w+)\s*\+\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m_nn_p39:
        col2_p39nn = m_nn_p39.group(1)
        col3_p39nn = m_nn_p39.group(2)
        if col2_p39nn in col_set and col3_p39nn in col_set and col_name not in (col2_p39nn, col3_p39nn):
            return {
                "derive_from": col2_p39nn,
                "expression": f"(value + row['{col3_p39nn}']) * random_float(0.0, 1.0)",
            }
    return None


def _match_date_right_ordering(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 41: col (>=|>|<=|<) DATE(other_col) — standalone comparison
    # with DATE() function wrapper. SQLite and PostgreSQL both support
    # ``DATE(col)`` to coerce a datetime/text to a date. The wrapper must
    # be stripped to extract the column name, then the comparison is
    # treated like Pattern 2/3/8 (standalone col vs other_col).
    # e.g., due_date >= DATE(period_start)
    # e.g., end_date <= DATE(start_date)  (unusual but valid)
    m = re.match(
        rf"^\s*{col}\s*(>=|>|<=|<)\s*DATE\s*\(\s*(\w+)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        op_p41 = m.group(1)
        other_col_p41 = m.group(2)
        if other_col_p41 in col_set and other_col_p41 != col_name:
            return _build_date_right_ordering(context, c, other_col_p41, op_p41)
    return None


def _match_inclusive_lower(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_date_col = context.is_date_col
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 2: col >= other_col (standalone, no NULL escape)
    # e.g., due_date >= invoice_date
    if m := re.match(rf"^\s*{col}\s*>=\s*(\w+)\s*$", expr, re.IGNORECASE):
        other_col = m.group(1)
        if other_col in col_set and other_col != col_name:
            if is_date_col:
                return {
                    "derive_from": other_col,
                    "expression": "value + timedelta(days=random_int(1, 30))",
                }
            if is_float_type:
                return {
                    "derive_from": other_col,
                    "expression": "value + random_float(1, 100)",
                }
            return {
                "derive_from": other_col,
                "expression": _INTEGER_ABOVE_SOURCE,
            }
    return None


def _match_exclusive_lower(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_date_col = context.is_date_col
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 3: col > other_col (standalone comparison — date or numeric)
    # For date columns (e.g., check_out > check_in): use timedelta to
    # guarantee the derived value is strictly greater than the source.
    # For float columns (e.g., unit_price > cost_price): multiply by a
    # factor > 1 to guarantee strict inequality.
    # For int columns: add a positive offset.
    if m := re.match(rf"^\s*{col}\s*>\s*(\w+)\s*$", expr, re.IGNORECASE):
        other_col = m.group(1)
        if other_col in col_set and other_col != col_name:
            if is_date_col or _is_date_column(other_col):
                return {
                    "derive_from": other_col,
                    "expression": "value + timedelta(days=random_int(1, 30))",
                }
            if is_float_type:
                return {
                    "derive_from": other_col,
                    "expression": "value * random_float(1.1, 2.0)",
                }
            return {
                "derive_from": other_col,
                "expression": _INTEGER_ABOVE_SOURCE,
            }
    return None


def _match_inclusive_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_date_col = context.is_date_col
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 8: col <= other_col (standalone — inclusive upper bound)
    # e.g., remaining_balance <= loan_amount, used_count <= total_count
    # For date columns: subtract a non-negative timedelta (0 days = equality).
    # For float columns (positive values): multiply by factor in [0.5, 1.0]
    #   (factor=1.0 gives equality, satisfying <=).
    # For int columns: generate random_int(0, value) — this guarantees
    #   0 <= result <= value, satisfying both col <= other_col AND
    #   col >= 0 (a common companion CHECK). The previous expression
    #   ``value - random_int(0, 100)`` could produce negative values
    #   when value < 100, violating col >= 0 constraints.
    # Note: float multiplication assumes positive source values (typical
    # for money/amount columns). For mixed-sign columns, the
    # ConstraintSolver's retry mechanism handles edge cases.
    if m := re.match(rf"^\s*{col}\s*<=\s*(\w+)\s*$", expr, re.IGNORECASE):
        other_col = m.group(1)
        if other_col in col_set and other_col != col_name:
            if is_date_col or _is_date_column(other_col):
                return {
                    "derive_from": other_col,
                    "expression": "value - timedelta(days=random_int(0, 365))",
                }
            if is_float_type:
                return {
                    "derive_from": other_col,
                    "expression": "value * random_float(0.5, 1.0)",
                }
            return {
                "derive_from": other_col,
                "expression": "random_int(0, value)",
            }
    return None


def _match_literal_lower_column_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 8a: col >= X AND col <= other_col (compound — lower bound literal + upper bound column)
    # e.g., remaining_balance >= 0 AND remaining_balance <= loan_amount
    # Derive from other_col, generate a value in [X, other_col] using
    # random_float/random_int with the literal X as min and the derived
    # value (other_col) as max. This guarantees both bounds are satisfied
    # when other_col >= X (typically ensured by other CHECK constraints
    # like loan_amount > 0).
    m = re.match(
        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        x_str, other_col = m.group(1), m.group(2)
        if other_col in col_set and other_col != col_name:
            if is_float_type:
                lower_float = float(x_str)
                return {
                    "derive_from": other_col,
                    "expression": f"random_float({lower_float}, value)",
                }
            x_val = int(x_str)
            return {
                "derive_from": other_col,
                "expression": f"random_int({x_val}, value)",
            }
    return None


def _match_column_lower_literal_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 8b: col >= other_col AND col <= Y (compound — lower bound column + upper bound literal)
    # e.g., discount_rate >= min_rate AND discount_rate <= 0.5
    # Derive from other_col, generate a value in [other_col, Y] using
    # random_float/random_int with the derived value as min and literal Y as max.
    m = re.match(
        rf"^\s*{col}\s*>=\s*(\w+)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        other_col, y_str = m.group(1), m.group(2)
        if other_col in col_set and other_col != col_name:
            if is_float_type:
                upper_float = float(y_str)
                return {
                    "derive_from": other_col,
                    "expression": f"random_float(value, {upper_float})",
                }
            y_val = int(y_str)
            return {
                "derive_from": other_col,
                "expression": f"random_int(value, {y_val})",
            }
    return None


def _match_exclusive_literal_lower_column_upper(
    context: _CrossColumnContext, c: dict[str, Any]
) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 8c: col > X AND col < other_col (compound — exclusive lower literal + exclusive upper column)
    # e.g., cost_price > 0 AND cost_price < unit_price
    # Derive from other_col, generate a value in (X, other_col) using
    # random_float/random_int. For floats, exclusive bounds are negligible
    # (probability of hitting exact bound is 0). For integers, shift by 1.
    m = re.match(
        rf"^\s*{col}\s*>\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        x_str, other_col = m.group(1), m.group(2)
        if other_col in col_set and other_col != col_name:
            if is_float_type:
                lower_float = float(x_str)
                return {
                    "derive_from": other_col,
                    "expression": f"random_float({lower_float}, value)",
                }
            x_val = int(x_str)
            return {
                "derive_from": other_col,
                "expression": f"random_int({x_val + 1}, value - 1)",
            }
    return None


def _match_exclusive_column_lower_literal_upper(
    context: _CrossColumnContext, c: dict[str, Any]
) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 8d: col > other_col AND col < Y (compound — exclusive lower column + exclusive upper literal)
    # e.g., end_time > start_time AND end_time < deadline
    # Derive from other_col, generate a value in (other_col, Y).
    m = re.match(
        rf"^\s*{col}\s*>\s*(\w+)\s+AND\s+{col}\s*<\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        other_col, y_str = m.group(1), m.group(2)
        if other_col in col_set and other_col != col_name:
            if is_float_type:
                upper_float = float(y_str)
                return {
                    "derive_from": other_col,
                    "expression": f"random_float(value, {upper_float})",
                }
            y_val = int(y_str)
            return {
                "derive_from": other_col,
                "expression": f"random_int(value + 1, {y_val - 1})",
            }
    return None


def _match_inclusive_literal_lower_exclusive_column_upper(
    context: _CrossColumnContext, c: dict[str, Any]
) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 8e: col >= X AND col < other_col (compound — inclusive lower literal + exclusive upper column)
    # e.g., deductible >= 0.0 AND deductible < coverage_amount
    # e.g., discount >= 0.0 AND discount < base_price
    # Derive from other_col, generate a value in [X, other_col) — always
    # strictly less than other_col to satisfy the exclusive upper bound.
    # For floats: use value * random_float(0.0, 0.99) when X=0 (common case),
    # or max(X, value * random_float(0.0, 0.99)) when X > 0. The factor 0.99
    # guarantees the result is strictly < value (since 0.99 < 1.0).
    # For integers: use random_int(X, value - 1) — safe when value > X
    # (guaranteed by well-formed schemas where other_col > X).
    m = re.match(
        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        x_str_8e, other_col_8e = m.group(1), m.group(2)
        if other_col_8e in col_set and other_col_8e != col_name:
            if is_float_type:
                if (lower_float := float(x_str_8e)) == 0:
                    return {
                        "derive_from": other_col_8e,
                        "expression": "value * random_float(0.0, 0.99)",
                    }
                return {
                    "derive_from": other_col_8e,
                    "expression": f"max({lower_float}, value * random_float(0.0, 0.99))",
                }
            x_val_8e = int(x_str_8e)
            return {
                "derive_from": other_col_8e,
                "expression": f"random_int({x_val_8e}, value - 1)",
            }
    return None


def _match_exclusive_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_date_col = context.is_date_col
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 9: col < other_col (standalone — strict upper bound)
    # e.g., transfer_fee < amount
    # For date columns: subtract a positive timedelta (>= 1 day).
    # For float columns (positive values): multiply by factor in [0.1, 0.9]
    #   (always strictly less than source).
    # For int columns: subtract a positive offset (>= 1).
    if m := re.match(rf"^\s*{col}\s*<\s*(\w+)\s*$", expr, re.IGNORECASE):
        other_col = m.group(1)
        if other_col in col_set and other_col != col_name:
            if is_date_col or _is_date_column(other_col):
                return {
                    "derive_from": other_col,
                    "expression": "value - timedelta(days=random_int(1, 365))",
                }
            if is_float_type:
                return {
                    "derive_from": other_col,
                    "expression": "value * random_float(0.1, 0.9)",
                }
            return {
                "derive_from": other_col,
                "expression": _INTEGER_BELOW_SOURCE,
            }
    return None


def _match_column_inequality(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col_type = context.col_type
    constraints = context.constraints
    all_columns = context.all_columns
    col = context.col
    col_set = context.col_set
    is_int_type = context.is_int_type
    expr = c.get("expression", "")
    # Pattern 6: col != other_col (inequality between two columns)
    # Handles both ``col != other_col`` and ``other_col != col`` (reversed).
    # Integer/FK variant: uses ``value - 1 if value > 1 else value + 1``
    # to guarantee inequality while staying within the valid FK range
    # (assumes sequential IDs starting from 1).
    # TEXT variant: when the column has a CHECK IN (...) constraint, builds
    # a rotation ternary that cycles through the IN set, guaranteeing the
    # result is always a different value from the set.
    # e.g., base_currency != quote_currency (both IN ('CNY','USD','EUR','HKD'))
    #   → 'USD' if value == 'CNY' else 'EUR' if value == 'USD' else ...
    other_col_p6: str | None = None
    if m_p6 := re.match(rf"^\s*{col}\s*!=\s*(\w+)\s*$", expr, re.IGNORECASE):
        other_col_p6 = m_p6.group(1)
    # Reversed form: other_col != col
    elif m_p6_rev := re.match(rf"^\s*(\w+)\s*!=\s*{col}\s*$", expr, re.IGNORECASE):
        other_col_p6 = m_p6_rev.group(1)
    if not other_col_p6 or other_col_p6 not in col_set or other_col_p6 == col_name:
        return None
    # Cycle prevention: only apply Pattern 6 to the column that comes
    # LATER in the column list. The constraint ``col != other_col`` is
    # symmetric — both columns match (one via direct form, the other via
    # reversed form). Without this check, both columns would derive_from
    # each other, creating a circular dependency that crashes the DAG.
    # By only applying to the later column, the earlier column is the
    # source (generated first), and the later column derives from it.
    col_idx_p6 = all_columns.index(col_name) if col_name in all_columns else -1
    other_idx_p6 = all_columns.index(other_col_p6) if other_col_p6 in all_columns else -1
    # UNIQUE-constraint guard: when col and other_col are BOTH part of
    # the same UNIQUE constraint, the deterministic expression
    # ``value - 1 if value > 1 else value + 1`` maps each other_col
    # value to exactly one col value. This limits the number of unique
    # (other_col, col) pairs to the number of distinct other_col values,
    # making large fills impossible (e.g., 1000 routes with 1000
    # warehouses — after 500 rows, collision probability is 50%).
    # Skip Pattern 6 and let the ConstraintSolver handle the ``!=``
    # constraint via retry logic with independent random FK sampling.
    p6_unique_conflict = any(
        uc.get("type") == "unique" and col_name in uc.get("columns", []) and other_col_p6 in uc.get("columns", [])
        for uc in constraints
    )
    should_apply_p6 = col_idx_p6 > other_idx_p6 and not p6_unique_conflict
    if should_apply_p6 and is_int_type:
        return {
            "derive_from": other_col_p6,
            "expression": "value - 1 if value > 1 else value + 1",
        }
    # TEXT columns: build a rotation ternary from the IN set.
    # Scan constraints for ``col IN ('v1', 'v2', ...)`` to extract
    # valid values, then cycle: each value maps to the next, last
    # maps to first. This guarantees result != value for any value
    # in the set.
    if not should_apply_p6 or col_type.upper() not in {"TEXT", "VARCHAR", "CHAR"}:
        return None
    return _build_inequality_enum_rotation(context, other_col_p6)


def _match_conditional_integer_equality(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 18: col != VALUE OR other_col = VALUE2 (conditional equality)
    # e.g., is_completed != 1 OR watched_percent = 100
    # Semantics: if col = VALUE, then other_col must = VALUE2.
    # Solution: derive col from other_col — set col = VALUE when
    # other_col = VALUE2, else set col to the opposite (1-VALUE for
    # boolean, 0 for non-boolean). This always satisfies the constraint:
    #   other_col = VALUE2 → col = VALUE → (VALUE != VALUE) OR (VALUE2 = VALUE2) → True
    #   other_col != VALUE2 → col = 1-VALUE → (1-VALUE != VALUE) OR (...) → True
    # Also handles the commutative form: other_col = VALUE2 OR col != VALUE
    p18_other: str | None = None
    p18_val: int = 0
    p18_val2: int = 0
    m18 = re.match(
        rf"^\s*{col}\s*!=\s*(\d+)\s+OR\s+(\w+)\s*=\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m18:
        p18_val = int(m18.group(1))
        p18_other = m18.group(2)
        p18_val2 = int(m18.group(3))
    else:
        # Try commutative form: other_col = VALUE2 OR col != VALUE
        m18 = re.match(
            rf"^\s*(\w+)\s*=\s*(\d+)\s+OR\s+{col}\s*!=\s*(\d+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m18:
            p18_other = m18.group(1)
            p18_val2 = int(m18.group(2))
            p18_val = int(m18.group(3))
    if m18 and p18_other and p18_other in col_set and p18_other != col_name:
        # For boolean columns (val in {0,1}): opposite is 1-val.
        # For other integer columns: opposite is 0 (safe default).
        opposite = 1 - p18_val if p18_val in {0, 1} else 0
        return {
            "derive_from": p18_other,
            "expression": f"{p18_val} if value == {p18_val2} else {opposite}",
        }
    return None


def _match_product_lower(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 7: col >= col1 * col2 (arithmetic comparison — two columns)
    # e.g., total_price >= unit_price * quantity
    # Derive from the first multiplicand, reference the second via the
    # row dict (ExpressionEngine supports row['col_name'] access).
    # The expression computes exactly col1 * col2, satisfying >= (equality).
    m = re.match(
        rf"^\s*{col}\s*>=\s*(\w+)\s*\*\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1, col2 = m.group(1), m.group(2)
        if col1 in col_set and col2 in col_set and col1 != col_name:
            return {
                "derive_from": col1,
                "expression": f"value * row['{col2}']",
            }
    return None


def _match_product_equality(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 7a: col = col1 * col2 (arithmetic equality — two columns)
    # e.g., subtotal = unit_price * quantity
    # Derive from the first multiplicand, reference the second via the
    # row dict. Same logic as Pattern 7 but for ``=`` (equality) instead
    # of ``>=``. Without this, ``subtotal = unit_price * quantity`` would
    # not be matched by the deterministic code (only by the LLM).
    m = re.match(
        rf"^\s*{col}\s*(?<![<>])=\s*(\w+)\s*\*\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1_p7a, col2_p7a = m.group(1), m.group(2)
        if col1_p7a in col_set and col2_p7a in col_set and col1_p7a != col_name:
            return {
                "derive_from": col1_p7a,
                "expression": f"value * row['{col2_p7a}']",
            }
    return None


def _match_multiplier_lower(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 7b: col >= col2 * CONSTANT (arithmetic comparison — column times literal)
    # e.g., base_price_yearly >= base_price_monthly * 10
    # Derive from col2, multiply by CONSTANT to exactly satisfy >= (equality).
    # The constant is a numeric literal (int or float), NOT a column name.
    m = re.match(
        rf"^\s*{col}\s*>=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        other_col_p7b, c_str_p7b = m.group(1), m.group(2)
        if other_col_p7b in col_set and other_col_p7b != col_name:
            c_val_p7b = float(c_str_p7b) if "." in c_str_p7b else int(c_str_p7b)
            return {
                "derive_from": other_col_p7b,
                "expression": f"value * {c_val_p7b}",
            }
    return None


def _match_binary_arithmetic(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 10: col = col1 + col2 (arithmetic equality — sum of two columns)
    # e.g., payment_amount = principal_portion + interest_portion
    # Derive from col1, reference col2 via the row dict. The expression
    # computes exactly col1 + col2, satisfying the equality constraint.
    # Supports +, -, and * operators (division excluded to avoid
    # zero-division errors).
    m = re.match(
        rf"^\s*{col}\s*=\s*(\w+)\s*([+\-*])\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1, op, col2 = m.group(1), m.group(2), m.group(3)
        if col1 in col_set and col2 in col_set and col1 != col_name:
            return {
                "derive_from": col1,
                "expression": f"value {op} row['{col2}']",
            }
    return None


def _match_sum_equality(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 11: col = col1 + col2 + col3 [+ col4 [+ ...]] (N-column addition equality, N >= 3)
    # e.g., total_amount = base_charge + weight_charge + distance_charge + fuel_surcharge + insurance_charge + tax
    # Derive from col1 (first operand), reference remaining cols via row dict.
    # The expression computes exactly col1 + col2 + ... + colN, satisfying the
    # equality constraint. Only supports + operator (most common case for
    # multi-column sums like invoices, totals, bills).
    m = re.match(
        rf"^\s*{col}\s*=\s*(\w+(?:\s*\+\s*\w+)+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        rhs = m.group(1)
        sum_cols = [c.strip() for c in rhs.split("+")]
        # Need at least 3 columns (2-column sums are handled by Pattern 10)
        if len(sum_cols) >= 3 and all(c in col_set for c in sum_cols) and sum_cols[0] != col_name:
            derive_col = sum_cols[0]
            ref_cols = sum_cols[1:]
            expr_parts = "value" + "".join(f" + row['{c}']" for c in ref_cols)
            return {
                "derive_from": derive_col,
                "expression": expr_parts,
            }
    return None


def _match_absolute_difference(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 42: col = abs(col1 - col2) (abs subtraction equality)
    # e.g., weight_diff = abs(total_weight_kg - billed_weight_kg)
    # Derive from col1, reference col2 via row dict. The expression computes
    # abs(value - row[col2]), satisfying the equality constraint.
    m = re.match(
        rf"^\s*{col}\s*=\s*abs\s*\(\s*(\w+)\s*-\s*(\w+)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1_p42, col2_p42 = m.group(1), m.group(2)
        if col1_p42 in col_set and col2_p42 in col_set and col1_p42 != col_name:
            return {
                "derive_from": col1_p42,
                "expression": f"abs(value - row['{col2_p42}'])",
            }
    return None


def _match_affine_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 43: col <= col2 * CONST1 + CONST2 (compound arithmetic upper bound)
    # e.g., estimated_hours <= distance_km * 0.5 + 24.0
    # Derive from col2, expression: value * CONST1 + random_float(0, CONST2)
    # (random offset 0..CONST2 ensures col <= col2 * CONST1 + CONST2).
    m = re.match(
        rf"^\s*{col}\s*<=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*\+\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col2_p43, const1_p43, const2_p43 = m.group(1), m.group(2), m.group(3)
        if col2_p43 in col_set and col2_p43 != col_name:
            return {
                "derive_from": col2_p43,
                "expression": f"value * {const1_p43} + random_float(0.0, {const2_p43})",
            }
    return None


def _match_product_quotient(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 44: col = col1 * col2 * col3 / CONST (3-column multiplication+division)
    # e.g., expected_interest = principal * interest_rate * term_months / 12.0
    # Derive from col1, reference col2 and col3 via row dict.
    m = re.match(
        rf"^\s*{col}\s*=\s*(\w+)\s*\*\s*(\w+)\s*\*\s*(\w+)\s*/\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1_p44, col2_p44, col3_p44, divisor_p44 = m.group(1), m.group(2), m.group(3), m.group(4)
        if col1_p44 in col_set and col2_p44 in col_set and col3_p44 in col_set and col1_p44 != col_name:
            return {
                "derive_from": col1_p44,
                "expression": f"value * row['{col2_p44}'] * row['{col3_p44}'] / {divisor_p44}",
            }
    return None


def _match_principal_plus_product(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 45: col = col1 + col1 * col2 * col3 / CONST (compound arithmetic with repeated column)
    # e.g., total_payable = principal + principal * interest_rate * term_months / 12.0
    # Derive from col1 (repeated), reference col2 and col3 via row dict.
    m = re.match(
        rf"^\s*{col}\s*=\s*(\w+)\s*\+\s*\1\s*\*\s*(\w+)\s*\*\s*(\w+)\s*/\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1_p45, col2_p45, col3_p45, divisor_p45 = m.group(1), m.group(2), m.group(3), m.group(4)
        if col1_p45 in col_set and col2_p45 in col_set and col3_p45 in col_set and col1_p45 != col_name:
            return {
                "derive_from": col1_p45,
                "expression": f"value + value * row['{col2_p45}'] * row['{col3_p45}'] / {divisor_p45}",
            }
    return None


def _match_reverse_sum(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    all_columns = context.all_columns
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 19: col1 + col2 = col (reverse sum equality — derive one addend from total)
    # e.g., insurance_covered + self_paid = total_amount
    # When current column is one of the addends (col1 or col2), derive it
    # from the total (col): col = total - other_addend.
    # Supports both orderings: "col + col1 = col2" and "col1 + col = col2".
    # Also supports subtraction: "col1 - col = col2" → col = col1 - col2.
    m = re.match(
        rf"^\s*(\w+)\s*([+\-])\s*{col}\s*=\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        # First ordering: "col1 <op> col = total" → groups: (col1, op, total)
        other_col, op, total_col = m.group(1), m.group(2), m.group(3)
    else:
        # Try reverse ordering: "col <op> col1 = total"
        m = re.match(
            rf"^\s*{col}\s*([+\-])\s*(\w+)\s*=\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            # Reverse ordering groups: (op, col1, total) — note the swap!
            op, other_col, total_col = m.group(1), m.group(2), m.group(3)
    if not m or other_col not in col_set or total_col not in col_set or (total_col == col_name):
        return None
    # Cycle prevention: the constraint ``col1 + col2 = total`` is
    # symmetric — both addends match Pattern 19 (one via first
    # ordering, the other via reverse). Without this check, both
    # would derive_from total and reference each other, creating a
    # circular dependency that crashes the DAG. By only applying
    # the ``total - other`` expression to the LATER column, the
    # earlier column becomes the source (generated first).
    col_idx_p19 = all_columns.index(col_name) if col_name in all_columns else -1
    other_idx_p19 = all_columns.index(other_col) if other_col in all_columns else -1
    if col_idx_p19 > other_idx_p19:
        # col1 + col = col2 → col = col2 - col1
        # col1 - col = col2 → col = col1 - col2
        # col + col1 = col2 → col = col2 - col1
        # col - col1 = col2 → col = col2 + col1
        if op == "+":
            return {
                "derive_from": total_col,
                "expression": f"value - row['{other_col}']",
            }
        # op == "-"
        return {
            "derive_from": total_col,
            "expression": f"row['{other_col}'] - value",
        }
    # col is the EARLIER addend. Derive it from total as an
    # integer fraction so that col ∈ [0, total] (when total >= 0).
    # This guarantees the LATER addend (total - col) is also in
    # [0, total], satisfying both ``col >= 0`` and
    # ``other_col >= 0`` CHECK constraints. Only applies to
    # addition (``col + other = total``); subtraction variants
    # (``col - other = total``) don't have the same non-negativity
    # guarantee, so we skip and let other patterns handle them.
    #
    # Uses ``random_int`` (not ``random_float``) to guarantee the
    # CHECK ``col1 + col2 = total`` holds EXACTLY in IEEE 754
    # floating point. Integers up to 2^53 are exactly representable
    # in double precision, and ``int + (float - int) = float`` is
    # exact for normal-range floats (the integer only affects the
    # integer part, leaving the fractional bits untouched). With
    # ``random_float``, the multiplication ``total * frac``
    # introduces rounding, and ``frac*total + (total - frac*total)``
    # may differ from ``total`` by 1 ULP, failing the ``=``
    # CHECK on REAL columns.
    if op != "+":
        return None
    return {
        "derive_from": total_col,
        "expression": "random_int(0, max(0, int(value)))",
    }


def _match_range_indicator(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 20: col = VALUE OR other_col < col2 OR other_col > col3 (range membership)
    # e.g., is_abnormal = 0 OR test_value < ref_lower OR test_value > ref_upper
    # Semantics: if col = VALUE, other_col must be in [col2, col3].
    # Solution: derive col from other_col — set col = VALUE when other_col
    # is in range, else set col to opposite (1-VALUE for boolean).
    # Expression: VALUE if (value >= row['col2'] and value <= row['col3']) else (1-VALUE)
    # This satisfies both:
    #   CHECK1: col = VALUE OR other_col < col2 OR other_col > col3
    #   CHECK2: col = (1-VALUE) OR (other_col >= col2 AND other_col <= col3)
    m = re.match(
        rf"^\s*{col}\s*=\s*(\d+)\s+OR\s+(\w+)\s*<\s*(\w+)\s+OR\s+\2\s*>\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str, other_col, col2, col3 = m.group(1), m.group(2), m.group(3), m.group(4)
        if other_col in col_set and col2 in col_set and col3 in col_set and other_col != col_name:
            val = int(val_str)
            opposite = 1 - val if val in {0, 1} else 0
            return {
                "derive_from": other_col,
                "expression": (f"{val} if (value >= row['{col2}'] and value <= row['{col3}']) else {opposite}"),
            }
    return None


def _match_average(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_int_type = context.is_int_type
    expr = c.get("expression", "")
    # Pattern 21: col = (col1 + col2 + col3) / N (average of N columns)
    # e.g., overall_score = (structural_score + electrical_score + plumbing_score) / 3
    # Derive from col1 (first addend), reference col2 + col3 via row dict.
    # The expression computes (value + row[col2] + row[col3]) / N, which
    # satisfies the equality. N must be a positive integer.
    # Also handles 2-column average: col = (col1 + col2) / 2
    # IMPORTANT: for INTEGER columns, SQLite uses integer division in
    # the CHECK constraint, but Python's ``/`` is float division.
    # Without ``int()`` wrapping, a non-divisible sum (e.g., 226/3=75.33)
    # would fail the CHECK (75.33 != 75) because SQLite evaluates CHECK
    # BEFORE applying column affinity. Wrap in ``int()`` to match
    # SQLite's integer division semantics.
    m = re.match(
        rf"^\s*{col}\s*=\s*\(\s*(\w+)\s*\+\s*(\w+)\s*(?:\+\s*(\w+)\s*)?\)\s*/\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    col1, col2, col3_opt, n_str = m.group(1), m.group(2), m.group(3), m.group(4)
    if col1 not in col_set or col2 not in col_set or col1 == col_name:
        return None
    n_val: float | int = float(n_str) if "." in n_str else int(n_str)
    # Wrap in int() for INTEGER columns to match SQLite's
    # integer division semantics in CHECK constraints.
    int_wrap = "int" if is_int_type else ""
    if col3_opt and col3_opt in col_set:
        # Three-column average: (value + row[col2] + row[col3]) / N
        inner = f"(value + row['{col2}'] + row['{col3_opt}']) / {n_val}"
        return {
            "derive_from": col1,
            "expression": f"{int_wrap}({inner})" if int_wrap else inner,
        }
    # Two-column average: (value + row[col2]) / N
    inner = f"(value + row['{col2}']) / {n_val}"
    return {
        "derive_from": col1,
        "expression": f"{int_wrap}({inner})" if int_wrap else inner,
    }


def _match_multiplier_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 22: col <= col2 * CONSTANT (percentage/scalar upper bound)
    # e.g., monthly_payment <= monthly_income * 0.5
    # e.g., discount_amount <= total_price * 0.3
    # Derive from col2, multiply by a random factor in [0, CONSTANT] to
    # guarantee col <= col2 * CONSTANT.
    m = re.match(
        rf"^\s*{col}\s*<=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        other_col, c_str = m.group(1), m.group(2)
        if other_col in col_set and other_col != col_name:
            c_val = float(c_str)
            # Generate a random factor in [0, c_val] so the derived
            # value is always <= other_col * c_val. Using 0 as the
            # lower bound allows zero (valid for <= constraints).
            return {
                "derive_from": other_col,
                "expression": f"value * random_float(0.0, {c_val})",
            }
    return None


def _match_threshold_indicator(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 23: col = VALUE OR col1 < X OR col2 < X OR col3 < X
    # (multi-column threshold — derive col as indicator of any column < X)
    # e.g., has_issues = 0 OR structural_score < 60 OR electrical_score < 60 OR plumbing_score < 60
    #
    # Semantics: the OR-chain ``col1 < X OR col2 < X OR ...`` is the
    # "escape" clause; ``col = VALUE`` is the "always-pass" case. The
    # CHECK fails ONLY when col != VALUE AND all columns >= X. Therefore:
    #   - When ANY column < X: col can be either VALUE or (1-VALUE); we
    #     choose (1-VALUE) because in the common dual-CHECK pattern
    #     (CHECK1: col = (1-VALUE) OR (all >= X)) the value is FORCED to
    #     (1-VALUE) here. Choosing (1-VALUE) satisfies BOTH CHECKs.
    #   - When ALL columns >= X: col MUST be VALUE (the only way CHECK2
    #     passes), and CHECK1 also passes (all >= X is true).
    #
    # Dual pattern (for reference, not matched here):
    #   CHECK1: col = (1-VALUE) OR (col1 >= X AND col2 >= X AND col3 >= X)
    # When both CHECKs are present, they together FORCE col to be:
    #   (1-VALUE) if (any < X) else VALUE
    # which is exactly what we produce below.
    #
    # Derive from col1 (first threshold column), reference others via row[...].
    # Also handles 2-column variant: col = VALUE OR col1 < X OR col2 < X
    m = re.match(
        rf"^\s*{col}\s*=\s*(\d+)\s+OR\s+(\w+)\s*<\s*(\d+)\s+OR\s+(\w+)\s*<\s*\3\s*(?:OR\s+(\w+)\s*<\s*\3)?\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str, col1, x_str, col2, col3_opt = (
            m.group(1),
            m.group(2),
            m.group(3),
            m.group(4),
            m.group(5),
        )
        if col1 in col_set and col2 in col_set and col1 != col_name:
            val = int(val_str)
            opposite = 1 - val if val in {0, 1} else 0
            x_val_p23: int = int(x_str)
            if col3_opt and col3_opt in col_set:
                # Three-column threshold. ``value`` refers to col1 (the
                # derive_from source). All three columns must be checked
                # against X — omitting ``value < {x_val}`` would silently
                # ignore col1's threshold, producing rows that violate the
                # CHECK when only col1 is below X.
                cond = f"value < {x_val_p23} or row['{col2}'] < {x_val_p23} or row['{col3_opt}'] < {x_val_p23}"
                return {
                    "derive_from": col1,
                    "expression": f"{opposite} if ({cond}) else {val}",
                }
            # Two-column threshold
            return {
                "derive_from": col1,
                "expression": f"{opposite} if (value < {x_val_p23} or row['{col2}'] < {x_val_p23}) else {val}",
            }
    return None


def _match_literal_or_comparison(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 24: col = VALUE OR col (>|>=|<|<=) other_col
    # (conditional comparison — col can be a fixed VALUE, or must satisfy
    # a comparison against another column)
    # e.g., base_price_first = 0.0 OR base_price_first > base_price_business
    # Semantics: col = VALUE is always allowed; col != VALUE is allowed
    # only when the comparison holds. We derive col from other_col:
    # 50% chance of VALUE, 50% chance of a value satisfying the comparison.
    m = re.match(
        rf"^\s*{col}\s*=\s*(-?\d+(?:\.\d+)?)\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    val_str, op, other_col = m.group(1), m.group(2), m.group(3)
    if other_col not in col_set or other_col == col_name:
        return None
    is_float_p24 = "." in val_str
    val_num_p24: float | int = float(val_str) if is_float_p24 else int(val_str)
    # Build expression that produces VALUE or a compliant value.
    # Use addition/subtraction (NOT multiplication) for float comparisons —
    # multiplication reverses inequality for negative values.
    comp_expr = _numeric_comparison_expression(op, is_float_p24)
    return {
        "derive_from": other_col,
        "expression": f"{val_num_p24} if random_int(0, 1) == 0 else {comp_expr}",
    }


def _match_conditional_comparison(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    constraints = context.constraints
    col = context.col
    col_set = context.col_set
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 24b: col1 != VALUE OR col (>=|>|<=|<) other_col
    # (inequality-first variant of Pattern 24 — col1 is compared with
    # inequality rather than equality)
    # e.g., status != 'paid' OR paid_amount >= total_amount
    # Semantics: when col1 == VALUE, col must satisfy the comparison
    # against other_col; otherwise col can be anything (use VALUE or a
    # safe default). Derive from other_col to ensure the comparison holds
    # when col1 == VALUE. When col1 != VALUE, use 0 (safe default).
    # 50% of the time when col1 != VALUE, use a value satisfying the
    # comparison anyway (more realistic distribution).
    m = re.match(
        rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    cond_col_p24b, val_str_p24b, op_p24b, other_col_p24b = (
        m.group(1),
        m.group(2),
        m.group(3),
        m.group(4),
    )
    if other_col_p24b not in col_set or other_col_p24b == col_name or cond_col_p24b not in col_set:
        return None
    # Cross-constraint cap: if there's also a ``col <= other_col``
    # or ``col < other_col`` constraint on the same column referencing
    # the same other_col, the comparison expression must NOT exceed
    # other_col. When op is >= or >, use ``value`` (exact equality)
    # to satisfy both >= and <= simultaneously.
    # e.g., ``status != 'paid' OR paid_amount >= total_amount`` +
    #       ``paid_amount <= total_amount`` → paid_amount == total_amount
    has_upper_cap = any(
        re.match(
            rf"^\s*{col}\s*(<=|<)\s*{other_col_p24b}\s*$",
            c2.get("expression", ""),
            re.IGNORECASE,
        )
        for c2 in constraints
        if c2.get("type") == "check"
    )
    if has_upper_cap and op_p24b in {">=", ">"}:
        # Exact equality satisfies both >= and <= constraints
        comp_expr_p24b = "value"
    else:
        comp_expr_p24b = _numeric_comparison_expression(op_p24b, is_float_type)
    # Derive from other_col; reference cond_col via row dict.
    # When cond_col == VALUE: produce compliant value.
    # When cond_col != VALUE: 50% compliant, 50% safe zero.
    safe_expr = "0.0" if is_float_type else "0"
    return {
        "derive_from": other_col_p24b,
        "expression": (
            f"{comp_expr_p24b} if row['{cond_col_p24b}'] == '{val_str_p24b}' "
            f"else ({comp_expr_p24b} if random_int(0, 1) == 0 else {safe_expr})"
        ),
    }


def _match_product_with_offset(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 25: col = col1 * col2 + col3 (multiplication + addition chain)
    # e.g., total_amount = unit_price * seat_count + tax_amount
    # Derive from col1 (first operand), reference col2 and col3 via row dict.
    # Also handles col = col1 * col2 - col3 (subtraction variant).
    m = re.match(
        rf"^\s*{col}\s*=\s*(\w+)\s*\*\s*(\w+)\s*([+\-])\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1, col2, sign, col3 = m.group(1), m.group(2), m.group(3), m.group(4)
        if col1 in col_set and col2 in col_set and col3 in col_set and col1 != col_name:
            return {
                "derive_from": col1,
                "expression": f"value * row['{col2}'] {sign} row['{col3}']",
            }
    return None


def _match_discounted_sum(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 38: col = (col1 + col2) * (CONST - col3) (complex arithmetic)
    # e.g., total_amount = (base_amount + seat_amount) * (1.0 - discount_rate)
    # Derive from col1 (first operand), reference col2 and col3 via row dict.
    # The CONST and col3 are in the subtraction term (1.0 - discount_rate).
    m = re.match(
        rf"^\s*{col}\s*=\s*\(\s*(\w+)\s*\+\s*(\w+)\s*\)\s*\*\s*\(\s*(-?\d+(?:\.\d+)?)\s*-\s*(\w+)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1_p38, col2_p38, const_p38, col3_p38 = (
            m.group(1),
            m.group(2),
            m.group(3),
            m.group(4),
        )
        if col1_p38 in col_set and col2_p38 in col_set and col3_p38 in col_set and col1_p38 != col_name:
            return {
                "derive_from": col1_p38,
                "expression": f"(value + row['{col2_p38}']) * ({const_p38} - row['{col3_p38}'])",
            }
    return None


def _match_literal_or_enum(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 26: col = VALUE OR other_col IN ('a', 'b', 'c')
    # (conditional enum — col = VALUE is always allowed; col != VALUE
    # is allowed only when other_col is in the enum set)
    # e.g., is_lead = 0 OR role IN ('captain', 'first_officer')
    # e.g., refund_amount = 0.0 OR booking_status IN ('cancelled', 'refunded')
    # Derive from other_col: set col to (1-VALUE) when other_col is in
    # the set, else VALUE. This satisfies the CHECK because:
    #   - When other_col IN set: col can be anything (CHECK passes)
    #   - When other_col NOT IN set: col must be VALUE (CHECK passes)
    m = re.match(
        rf"^\s*{col}\s*=\s*(-?\d+(?:\.\d+)?)\s+OR\s+(\w+)\s+IN\s*\(([^)]+)\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    val_str, other_col, values_str = m.group(1), m.group(2), m.group(3)
    if other_col not in col_set or other_col == col_name:
        return None
    # Parse the values: 'a', 'b', 'c' → ['a', 'b', 'c']
    if not (values := re.findall(_SINGLE_QUOTED_VALUE, values_str)):
        values = re.findall(_DOUBLE_QUOTED_VALUE, values_str)
    if not values:
        return None
    is_float_p26 = "." in val_str
    val_num_p26: float | int = float(val_str) if is_float_p26 else int(val_str)
    # Build Python list literal: ['captain', 'first_officer']
    py_list = "[" + ", ".join(f"'{v}'" for v in values) + "]"
    # For int/boolean columns, use (1-VALUE); for float,
    # use a random positive amount when allowed.
    if is_float_p26:
        non_val_expr = "random_float(0.01, 100.0)"
    else:
        non_val_expr = str(1 - val_num_p26) if val_num_p26 in {0, 1} else "0"
    return {
        "derive_from": other_col,
        "expression": f"{non_val_expr} if value in {py_list} else {val_num_p26}",
    }


def _match_conditional_enum(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 26b: col1 != VALUE OR col IN ('a', 'b', 'c')
    # (inequality-first variant of Pattern 26 — col1 is compared with
    # inequality rather than equality)
    # e.g., scope != 'global' OR action IN ('admin', 'read')
    # Semantics: when col1 == VALUE, col must be in the enum set;
    # otherwise col can be anything. Derive from col1: when col1 == VALUE,
    # pick a random value from the set; otherwise pick the first set
    # value (safe default). The expression references the parsed set
    # via random_choice-style selection.
    m = re.match(
        rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s+IN\s*\(([^)]+)\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        cond_col_p26b, val_str_p26b, values_str_p26b = (
            m.group(1),
            m.group(2),
            m.group(3),
        )
        if cond_col_p26b in col_set and cond_col_p26b != col_name:
            # Parse the values: 'a', 'b', 'c' → ['a', 'b', 'c']
            if not (values_p26b := re.findall(_SINGLE_QUOTED_VALUE, values_str_p26b)):
                values_p26b = re.findall(_DOUBLE_QUOTED_VALUE, values_str_p26b)
            if values_p26b:
                py_list_p26b = "[" + ", ".join(f"'{v}'" for v in values_p26b) + "]"
                first_val_p26b = values_p26b[0]
                # When cond_col == VALUE: pick from the set (satisfies IN).
                # When cond_col != VALUE: use first set value (safe default).
                return {
                    "derive_from": cond_col_p26b,
                    "expression": (
                        f"{py_list_p26b}[random_int(0, {len(values_p26b) - 1})] "
                        f"if value == '{val_str_p26b}' else '{first_val_p26b}'"
                    ),
                }
    return None


def _match_conditional_enum_equalities(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 26c: col1 != VALUE OR col = 'V1' OR col = 'V2' [OR col = 'V3' ...]
    # (explicit OR-equality variant of Pattern 26b — instead of IN(), the
    # CHECK uses ``col = 'V1' OR col = 'V2'`` syntax)
    # e.g., scope != 'global' OR action = 'admin' OR action = 'read'
    # Semantics: when col1 == VALUE, col must be one of V1, V2, ...;
    # otherwise col can be anything. Derive from col1: when col1 == VALUE,
    # pick a random value from the set; otherwise pick the first set value.
    m = re.match(
        rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*=\s*'([^']+)'\s*(?:OR\s+{col}\s*=\s*'([^']+)'\s*)+\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        cond_col_p26c = m.group(1)
        val_str_p26c = m.group(2)
        # Extract all quoted values after the OR keywords.
        if (
            cond_col_p26c in col_set
            and cond_col_p26c != col_name
            and (all_values_p26c := re.findall(rf"{col}\s*=\s*'([^']+)'", expr, re.IGNORECASE))
        ):
            py_list_p26c = "[" + ", ".join(f"'{v}'" for v in all_values_p26c) + "]"
            first_val_p26c = all_values_p26c[0]
            return {
                "derive_from": cond_col_p26c,
                "expression": (
                    f"{py_list_p26c}[random_int(0, {len(all_values_p26c) - 1})] "
                    f"if value == '{val_str_p26c}' else '{first_val_p26c}'"
                ),
            }
    return None


def _match_conditional_dual_ranges(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 36: N-way conditional range with dual bounds (both lower AND upper per clause)
    #   (other_col = 'V1' AND col >= X1 AND col (<|<=) Y1) OR
    #   (other_col = 'V2' AND col >= X2 AND col (<|<=) Y2) OR [...]
    # Each clause constrains col to a specific range [X, Y) or [X, Y]
    # based on other_col's value. Derive col from other_col and emit a
    # nested ternary that picks the appropriate random range per enum.
    # e.g., (risk_category = 'low' AND risk_score >= 1 AND risk_score < 25) OR
    #       (risk_category = 'medium' AND risk_score >= 25 AND risk_score < 50) OR
    #       (risk_category = 'high' AND risk_score >= 50 AND risk_score < 75) OR
    #       (risk_category = 'critical' AND risk_score >= 75 AND risk_score <= 100)
    # For integers: ``random_int(X, Y-1)`` for ``< Y``, ``random_int(X, Y)`` for ``<= Y``.
    # For floats: ``random_float(X, Y-0.01)`` for ``< Y``, ``random_float(X, Y)`` for ``<= Y``.
    # Handles newlines/multi-whitespace in CHECK expressions by normalizing
    # before the guard check (SQLite stores table-level CHECKs with newlines).
    expr_norm = re.sub(r"\s+", " ", expr).strip()
    if " OR " not in expr_norm or _SQL_AND not in expr_norm:
        return None
    clause_re_36 = (
        rf"\(?\s*(\w+)\s*=\s*'([^']+)'\s+AND\s+{col}\s*"
        r"(>=|>)\s*(-?[0-9]+(?:\.[0-9]+)?)\s+AND\s+"
        rf"{col}\s*(<=|<)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*\)?"
    )
    clauses_36 = re.findall(clause_re_36, expr)
    if len(clauses_36) < 2:
        return None
    other_col_p36 = clauses_36[0][0]
    if (
        other_col_p36 not in col_set
        or other_col_p36 == col_name
        or (not all(cl[0] == other_col_p36 for cl in clauses_36))
    ):
        return None
    parts_p36: list[str] = []
    for clause in clauses_36[:-1]:
        rand_e = _dual_bound_random_expression(clause, is_float_type)
        parts_p36.append(f"{rand_e} if value == '{clause[1]}'")
    # Last clause is the fallback.
    last_rand_36 = _dual_bound_random_expression(clauses_36[-1], is_float_type)
    expr_chain_36 = last_rand_36
    for idx in range(len(parts_p36) - 1, -1, -1):
        expr_chain_36 = f"{parts_p36[idx]} else ({expr_chain_36})"
    return {
        "derive_from": other_col_p36,
        "expression": expr_chain_36,
    }


def _match_conditional_ranges(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    expr_norm = re.sub(r"\s+", " ", expr).strip()
    # Pattern 27: N-way conditional range (single bound per clause)
    #   other_col = 'V1' AND col OP1 X1 OR other_col = 'V2' AND col OP2 X2 [OR ...]
    # where OPi ∈ {<=, <, >=, >} and each clause constrains col based on
    # other_col's value. Derive col from other_col and emit a nested
    # ternary that picks the appropriate random range for each enum value.
    # e.g., bag_type = 'carry_on' AND weight_kg <= 10.0
    #       OR bag_type = 'checked' AND weight_kg <= 32.0
    #       OR bag_type = 'oversized' AND weight_kg > 32.0
    # This pattern handles 2-4 clauses. Clauses with ``<= X`` produce
    # ``random_float(0.01, X)``; ``>= X`` produces ``random_float(X, X+100)``;
    # ``> X`` produces ``random_float(X+0.01, X+100)`` (epsilon for strict
    # inequality); ``< X`` produces ``random_float(0.01, X-0.01)``.
    # Uses ``expr_norm`` (whitespace-normalized) for the guard check to
    # handle SQLite table-level CHECKs stored with newlines.
    if " OR " not in expr_norm or _SQL_AND not in expr_norm:
        return None
    clause_re = (
        rf"(\w+)\s*=\s*'([^']+)'\s+AND\s+{col}\s*"
        r"(>=|<=|>|<)\s*(-?[0-9]+(?:\.[0-9]+)?)"
    )
    clauses = re.findall(clause_re, expr)
    # Require at least 2 clauses AND that the whole expr is exactly
    # the OR-chain (no extra terms). Each clause: (other_col, Vi, OPi, Xi).
    if len(clauses) < 2:
        return None
    # Verify all clauses reference the SAME other column
    other_col_p27 = clauses[0][0]
    if other_col_p27 not in col_set or other_col_p27 == col_name or (not all(cl[0] == other_col_p27 for cl in clauses)):
        return None
    # Build nested ternary: ``rand_a if value=='V1' else (rand_b if value=='V2' else rand_c)``
    # Last clause is the fallback.
    parts_p27: list[str] = []
    for _other, vi, opi, xi in clauses[:-1]:
        xi_num = float(xi)
        rand_expr = _range_expr_for_op(opi, xi_num)
        parts_p27.append(f"{rand_expr} if value == '{vi}'")
    _other, _last_vi, last_op, last_xi = clauses[-1]
    last_rand = _range_expr_for_op(last_op, float(last_xi))
    # Chain with ``else (next)`` and final ``else <fallback>``
    expr_chain = last_rand
    for idx in range(len(parts_p27) - 1, -1, -1):
        expr_chain = f"{parts_p27[idx]} else ({expr_chain})"
    return {
        "derive_from": other_col_p27,
        "expression": expr_chain,
    }


def _match_conditional_string_mapping(
    context: _CrossColumnContext, _constraint: dict[str, Any]
) -> dict[str, Any] | None:
    constraints = context.constraints
    # Pattern 37 string variant: multiple ``col1 != VALUE_i OR col = 'VALUE2_i'``
    # on same column (multi-conditional cross-column with string equality).
    # When 2+ separate CHECK constraints constrain the SAME target column
    # to a specific STRING value based on the SAME enum column's value,
    # derive col from the enum column with a nested ternary mapping each
    # enum value to its required string.
    # e.g., R6.transactions.direction has:
    #   CHECK (txn_type != 'withdrawal' OR direction = 'out')
    #   CHECK (txn_type != 'deposit' OR direction = 'in')
    #   CHECK (txn_type != 'fee' OR direction = 'out')
    #   CHECK (txn_type != 'interest' OR direction = 'in')
    # Derive from txn_type: 'out' if withdrawal, 'in' if deposit, etc.
    # Default branch: pick the first VALUE2 (guaranteed valid for any
    # enum value not explicitly listed).
    p37s_branches: list[tuple[str, str]] = []
    p37s_other_col: str | None = None
    for c_p37s in constraints:
        if (branch := _match_conditional_string_clause(context, c_p37s)) is None:
            continue
        other_p37s, val_p37s, eq_val_p37s = branch
        if p37s_other_col is None:
            p37s_other_col = other_p37s
        elif p37s_other_col != other_p37s:
            continue
        p37s_branches.append((val_p37s, eq_val_p37s))
    if p37s_other_col is None or len(p37s_branches) < 2:
        return None
    # Build nested ternary: 'V2_1' if value == 'V1' else ('V2_2' if value == 'V2' else (... else default))
    default_p37s = f"'{p37s_branches[0][1]}'"
    expr_p37s_final = default_p37s
    for val_p37s, eq_val_p37s in reversed(p37s_branches):
        expr_p37s_final = f"'{eq_val_p37s}' if value == '{val_p37s}' else ({expr_p37s_final})"
    return {
        "derive_from": p37s_other_col,
        "expression": expr_p37s_final,
    }


def _match_conditional_string_clause(
    context: _CrossColumnContext, constraint: dict[str, Any]
) -> tuple[str, str, str] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    if constraint.get("type") != "check":
        return None
    if not (expr_p37s := constraint.get("expression", "")):
        return None
    m_p37s = re.match(
        rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*=\s*'([^']*)'\s*$",
        expr_p37s,
        re.IGNORECASE,
    )
    if not m_p37s:
        return None
    other_p37s, val_p37s, eq_val_p37s = (
        m_p37s.group(1),
        m_p37s.group(2),
        m_p37s.group(3),
    )
    if other_p37s not in col_set or other_p37s == col_name:
        return None
    return other_p37s, val_p37s, eq_val_p37s


def _match_conditional_numeric_mapping(
    context: _CrossColumnContext, _constraint: dict[str, Any]
) -> dict[str, Any] | None:
    # Pattern 37: multiple ``col1 != VALUE_i OR col OP_i X_i`` on same column
    # (multi-conditional cross-column — when 2+ separate CHECK constraints
    # constrain the SAME target column based on the SAME enum column's value)
    # e.g.:
    #   CHECK (movement_type != 'inbound' OR quantity > 0)
    #   CHECK (movement_type != 'outbound' OR quantity < 0)
    #   CHECK (movement_type != 'adjustment' OR quantity != 0)
    # Each constraint means: "when col1 == VALUE_i, col must satisfy OP_i X_i".
    # Derive col from col1 and emit a nested ternary with a branch per VALUE.
    # Branches:
    #   ``> X``  → random_int(X+1, X+100) or random_float(X+0.01, X+100.0)
    #   ``>= X`` → random_int(X, X+100) or random_float(X, X+100.0)
    #   ``< X``  → random_int(X-100, X-1) or random_float(X-100.0, X-0.01)
    #   ``<= X`` → random_int(X-100, X) or random_float(X-100.0, X)
    #   ``!= X`` → random non-X value (pick from positive or negative range)
    # Default branch (col1 not in any VALUE set): random_int(-100, 100).
    # This pattern MUST run before Pattern 28 (single-condition case) so
    # the multi-branch expression wins when 2+ conditions exist.
    p37_other_col, p37_branches = _collect_conditional_numeric_branches(context)
    if p37_other_col is not None and len(p37_branches) >= 2:
        # Build nested ternary: branch1 if value == 'V1' else (branch2 if value == 'V2' else ... else default)
        use_float = any(b[3] for b in p37_branches)
        parts_p37: list[str] = []
        for val_p37, op_p37, x_p37, _ in p37_branches:
            branch = _conditional_numeric_branch(use_float, op_p37, x_p37)
            parts_p37.append(f"{branch} if value == '{val_p37}'")
        # Default branch: covers enum values not in any VALUE set
        default_p37 = "random_float(-100.0, 100.0)" if use_float else "random_int(-100, 100)"
        # Build nested ternary: a if cond1 else (b if cond2 else (... else default))
        expr_p37_final = default_p37
        for cond_p37 in reversed(parts_p37):
            expr_p37_final = f"{cond_p37} else ({expr_p37_final})"
        return {
            "derive_from": p37_other_col,
            "expression": expr_p37_final,
        }
    return None


def _match_disjunction_indicator(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 46: col = INT_VALUE OR other_col (<|<=) CONST [OR ...]
    # (multi-clause disjunction with integer equality as first clause)
    # e.g., is_free = 1 OR price < 100 OR original_price IS NULL OR original_price < 200
    # Semantics: the CHECK is satisfied if ANY clause is true. When
    # other_col violates the inequality (>= CONST for <, > CONST for <=),
    # col MUST be INT_VALUE to satisfy the first clause. When other_col
    # satisfies the inequality, col can be any valid value (the second
    # clause is already true). Derive from other_col: set col to INT_VALUE
    # when the inequality would fail, else random_int(0, INT_VALUE).
    # This is a conservative approach — setting col = INT_VALUE is always
    # safe because it satisfies the first clause regardless of other cols.
    m = re.match(
        rf"^\s*{col}\s*=\s*(\d+)\s+OR\s+(\w+)\s*(<|<=)\s*(-?\d+(?:\.\d+)?)\s*(?:OR\s+.*)?$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_p46 = int(m.group(1))
        other_col_p46 = m.group(2)
        op_p46 = m.group(3)
        threshold_p46 = float(m.group(4))
        if other_col_p46 in col_set and other_col_p46 != col_name:
            # When other_col violates the inequality, col MUST be INT_VALUE.
            violate_expr = f"value >= {threshold_p46}" if op_p46 == "<" else f"value > {threshold_p46}"
            return {
                "derive_from": other_col_p46,
                "expression": f"{val_p46} if {violate_expr} else random_int(0, {val_p46})",
            }
    return None


def _match_conditional_positive(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    constraints = context.constraints
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 28: col1 != VALUE OR col2 > 0
    # (conditional requirement — when col1 == VALUE, col2 must be > 0;
    # otherwise col2 can be anything, including 0)
    # e.g., bag_type != 'oversized' OR fee_amount > 0.0
    # e.g., status != 'approved' OR approved_amount > 0.0
    # Derive from col1: when col1 == VALUE, set col2 to a positive random
    # value; otherwise set col2 to 0 (or empty for strings).
    #
    # Cross-column upper bound awareness: if another CHECK constrains
    # ``col <= other_upper_col`` (or ``col < other_upper_col``), the
    # hardcoded upper bound (threshold + 100.0) may exceed
    # other_upper_col, causing CHECK violations at fill time. When such
    # a constraint exists, cap the positive expression with
    # ``min(random_float(...), row['other_upper_col'])`` to guarantee
    # the upper bound is respected. The ``min`` function is in
    # SAFE_FUNCTIONS (see core/expression.py).
    m = re.match(
        rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*>\s*(-?[0-9]+(?:\.[0-9]+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    other_col_p28, val_str_p28, threshold_str = m.group(1), m.group(2), m.group(3)
    if other_col_p28 not in col_set or other_col_p28 == col_name:
        return None
    threshold = float(threshold_str)
    # When col1 == VALUE: col2 must be > threshold. Use
    # threshold+0.01 as the lower bound (epsilon for strict >).
    positive_expr = f"random_float({threshold + 0.01}, {threshold + 100.0})"
    # Check for other CHECKs that constrain col <= other_col
    # or col < other_col (cross-column upper bound). If found,
    # cap the positive expression to respect the upper bound.
    for other_c_p28 in constraints:
        if other_c_p28 is c:
            continue
        if other_c_p28.get("type") != "check":
            continue
        other_expr_p28 = other_c_p28.get("expression", "")
        m_upper_p28 = re.search(
            rf"{col}\s*(<=|<)\s*(\w+)",
            other_expr_p28,
            re.IGNORECASE,
        )
        if m_upper_p28:
            upper_col_p28 = m_upper_p28.group(2)
            if upper_col_p28 in col_set and upper_col_p28 != col_name:
                positive_expr = f"min({positive_expr}, row['{upper_col_p28}'])"
                break
    # When col1 != VALUE: col2 can be 0 (or any value >= 0).
    zero_expr = "0.0"
    return {
        "derive_from": other_col_p28,
        "expression": f"{positive_expr} if value == '{val_str_p28}' else {zero_expr}",
    }


def _match_absolute_left_arithmetic(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 12: col = abs(col1) (*|+|-) col2 (abs() wrapper on first operand)
    # e.g., total_value = abs(quantity) * price_per_unit
    # Derive from col1 (the column inside abs()), reference col2 via row dict.
    # The expression computes abs(col1) {op} col2, satisfying the equality.
    # ``abs`` is in SAFE_FUNCTIONS (see core/expression.py line 53).
    # Supports +, -, * operators (division excluded to avoid zero-division).
    m = re.match(
        rf"^\s*{col}\s*=\s*abs\s*\(\s*(\w+)\s*\)\s*([+\-*])\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1, op, col2 = m.group(1), m.group(2), m.group(3)
        if col1 in col_set and col2 in col_set and col1 != col_name:
            return {
                "derive_from": col1,
                "expression": f"abs(value) {op} row['{col2}']",
            }
    return None


def _match_absolute_right_arithmetic(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 13: col = col1 (*|+|-) abs(col2) (abs() wrapper on second operand)
    # e.g., net_value = price_per_unit * abs(quantity)
    # Derive from col1, apply abs() to the row-referenced second operand.
    m = re.match(
        rf"^\s*{col}\s*=\s*(\w+)\s*([+\-*])\s*abs\s*\(\s*(\w+)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1, op, col2 = m.group(1), m.group(2), m.group(3)
        if col1 in col_set and col2 in col_set and col1 != col_name:
            return {
                "derive_from": col1,
                "expression": f"value {op} abs(row['{col2}'])",
            }
    return None


def _match_absolute_product(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 14: col = abs(col1) * abs(col2) (abs() wrappers on both operands)
    # e.g., total = abs(delta_a) * abs(delta_b)
    # Derive from col1, apply abs() to both operands.
    m = re.match(
        rf"^\s*{col}\s*=\s*abs\s*\(\s*(\w+)\s*\)\s*\*\s*abs\s*\(\s*(\w+)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1, col2 = m.group(1), m.group(2)
        if col1 in col_set and col2 in col_set and col1 != col_name:
            return {
                "derive_from": col1,
                "expression": f"abs(value) * abs(row['{col2}'])",
            }
    return None


def _match_absolute_value(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 15: col = abs(col1) (standalone abs — magnitude)
    # e.g., magnitude = abs(delta)
    # Derive from col1, apply abs() to value.
    m = re.match(
        rf"^\s*{col}\s*=\s*abs\s*\(\s*(\w+)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1 = m.group(1)
        if col1 in col_set and col1 != col_name:
            return {
                "derive_from": col1,
                "expression": "abs(value)",
            }
    return None


def _match_three_operand_arithmetic(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 29: col = col1 (+|-) col2 (+|-) col3 (three-column arithmetic
    # chain with mixed + and - operators)
    # e.g., available = balance + credit_limit - held
    # e.g., net_amount = gross_amount - discount + tax
    # Derive from col1 (first operand), reference col2 and col3 via row dict.
    # The expression computes value {op1} row[col2] {op2} row[col3],
    # satisfying the equality.
    m = re.match(
        rf"^\s*{col}\s*=\s*(\w+)\s*([+\-])\s*(\w+)\s*([+\-])\s*(\w+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        col1, op1, col2, op2, col3 = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        if col1 in col_set and col2 in col_set and col3 in col_set and col1 != col_name:
            return {
                "derive_from": col1,
                "expression": f"value {op1} row['{col2}'] {op2} row['{col3}']",
            }
    return None


def _match_conditional_null_value(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 30: col1 != VALUE OR col IS NULL (conditional NULL — when
    # col1 == VALUE, col must be NULL; otherwise col can be anything)
    # e.g., position != 'ceo' OR manager_id IS NULL
    # e.g., status != 'closed' OR closed_at IS NULL
    # Derive from col1: when col1 == VALUE, set col to None; otherwise
    # set col to a safe value. For FK columns (integer), returning None
    # is the safest approach — it avoids FK violations while satisfying
    # the CHECK. For non-FK columns, None is also valid (SQLite allows
    # NULL unless NOT NULL is specified).
    # NOTE: the ``None`` literal is supported by the expression engine
    # (simpleeval evaluates Python None). The orchestrator's derive_from
    # handler accepts None as a valid value (stored as NULL in the DB).
    # ADVERSARIAL FIX: for FK columns, the non-null branch previously
    # returned ``0`` (for int) — but ``0`` is NEVER a valid FK value
    # (auto-increment IDs start from 1). This caused FK violations at
    # fill time. Now, FK columns return ``None`` for BOTH branches,
    # making the column always NULL. This is semantically acceptable
    # because FK columns in Pattern 30 are nullable (the CHECK requires
    # IS NULL for some values, so the column must be nullable).
    m = re.match(
        rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s+IS\s+NULL\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        other_col_p30, val_str_p30 = m.group(1), m.group(2)
        if other_col_p30 in col_set and other_col_p30 != col_name:
            # When col1 == VALUE: col = None (NULL)
            # When col1 != VALUE: col = a safe default (0 for int, 0.0 for float)
            # For FK columns: always None (0 is never a valid FK id)
            null_expr = "None"
            non_null_expr = _conditional_fallback_literal(context, "None")
            return {
                "derive_from": other_col_p30,
                "expression": f"{null_expr} if value == '{val_str_p30}' else {non_null_expr}",
            }
    return None


def _match_conditional_nonnull(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 30b: col1 = VALUE OR col IS NOT NULL (reverse of Pattern 30 —
    # when col1 == VALUE, col can be anything including NULL; when col1 !=
    # VALUE, col must be NOT NULL)
    # e.g., org_type = 'root' OR parent_id IS NOT NULL
    # Derive from col1: when col1 == VALUE, set col to None (NULL is allowed);
    # when col1 != VALUE, set col to a safe non-NULL value. For FK columns,
    # use ``1`` (the first autoincrement id, valid after the first row is
    # inserted). For non-FK columns, use ``0`` (int) or ``0.0`` (float).
    # NOTE: this pattern often coexists with Pattern 30 on the same column
    # (e.g., ``org_type != 'root' OR parent_id IS NULL`` + ``org_type =
    # 'root' OR parent_id IS NOT NULL``), which together mean: parent_id is
    # NULL iff org_type == 'root'. Pattern 30 runs first and returns
    # ``None if value == 'root' else None`` for FK columns (always NULL).
    # Pattern 30b overrides this for the non-VALUE branch to be non-NULL.
    # However, since Pattern 30 already returned, Pattern 30b only fires
    # when Pattern 30 did NOT match (i.e., the CHECK uses ``= VALUE``
    # instead of ``!= VALUE``).
    m = re.match(
        rf"^\s*(\w+)\s*=\s*'([^']+)'\s+OR\s+{col}\s+IS\s+NOT\s+NULL\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        other_col_p30b, val_str_p30b = m.group(1), m.group(2)
        if other_col_p30b in col_set and other_col_p30b != col_name:
            # When col1 == VALUE: col = None (NULL is allowed)
            # When col1 != VALUE: col = non-NULL
            # For FK columns: use 1 (first autoincrement id, valid after first row)
            # For non-FK columns: use 0 (int) or 0.0 (float)
            non_null_expr_p30b = _conditional_fallback_literal(context, "1")
            return {
                "derive_from": other_col_p30b,
                "expression": f"None if value == '{val_str_p30b}' else {non_null_expr_p30b}",
            }
    return None


def _match_conditional_integer_nonnull(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 30b (int variant): col1 = INTEGER_VALUE OR col IS NOT NULL
    # e.g., level = 1 OR parent_id IS NOT NULL
    # Same semantics as the string variant but with an unquoted integer VALUE.
    # When col1 == INT_VALUE: col = None (NULL is allowed);
    # when col1 != INT_VALUE: col = non-NULL (1 for FK, 0/0.0 for others).
    m_int_p30b = re.match(
        rf"^\s*(\w+)\s*=\s*(\d+)\s+OR\s+{col}\s+IS\s+NOT\s+NULL\s*$",
        expr,
        re.IGNORECASE,
    )
    if m_int_p30b:
        other_col_p30b_int, val_int_p30b = m_int_p30b.group(1), m_int_p30b.group(2)
        if other_col_p30b_int in col_set and other_col_p30b_int != col_name:
            non_null_expr_p30b_int = _conditional_fallback_literal(context, "1")
            return {
                "derive_from": other_col_p30b_int,
                "expression": f"None if value == {val_int_p30b} else {non_null_expr_p30b_int}",
            }
    return None


def _match_conditional_not_in_nonnull(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col_type = context.col_type
    col = context.col
    col_set = context.col_set
    is_float_type = context.is_float_type
    is_fk_column = context.is_fk_column
    expr = c.get("expression", "")
    # Pattern 30b (NOT IN variant): col1 NOT IN ('v1','v2',...) OR col IS NOT NULL
    # (when col1 IS in the set, col must be NOT NULL; when col1 is NOT in
    # the set, col can be NULL). This is the multi-value variant of
    # Pattern 30b (which handles ``col1 = 'VALUE' OR col IS NOT NULL``).
    # e.g., status NOT IN ('approved', 'settled') OR approved_amount IS NOT NULL
    # Derive from col1: when col1 NOT IN the set, set col to None (NULL
    # allowed); when col1 IN the set, set col to a safe non-NULL value.
    # For FK columns, use ``1`` (first autoincrement id). For float
    # columns, use ``random_float(0.01, 1000.0)`` (positive, satisfies
    # ``> 0.0`` CHECKs). For int columns, use ``random_int(1, 1000)``.
    m_notin_p30b = re.match(
        rf"^\s*(\w+)\s+NOT\s+IN\s*\(([^)]+)\)\s+OR\s+{col}\s+IS\s+NOT\s+NULL\s*$",
        expr,
        re.IGNORECASE,
    )
    if m_notin_p30b:
        other_col_p30b_notin = m_notin_p30b.group(1)
        values_str_p30b_notin = m_notin_p30b.group(2)
        if other_col_p30b_notin in col_set and other_col_p30b_notin != col_name:
            # Parse the value list: 'v1', 'v2', ...
            values_p30b_notin = re.findall(_SINGLE_QUOTED_VALUE, values_str_p30b_notin)
            values_repr_p30b_notin = ", ".join(f"'{v}'" for v in values_p30b_notin)
            if is_fk_column:
                non_null_expr_p30b_notin = "1"
            elif is_float_type:
                non_null_expr_p30b_notin = "random_float(0.01, 1000.0)"
            elif "INT" in col_type.upper():
                non_null_expr_p30b_notin = "random_int(1, 1000)"
            else:
                non_null_expr_p30b_notin = "'0'"
            return {
                "derive_from": other_col_p30b_notin,
                "expression": f"None if value not in ({values_repr_p30b_notin}) else {non_null_expr_p30b_notin}",
            }
    return None


def _match_conditional_numeric_equality(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 31: col1 != VALUE OR col = VALUE2 (conditional equality —
    # when col1 == VALUE, col must be exactly VALUE2; otherwise col can
    # be anything)
    # e.g., status != 'paid_off' OR remaining = 0.0
    # e.g., type != 'completed' OR fee = 0.0
    # Derive from col1: when col1 == VALUE, set col to VALUE2; otherwise
    # set col to a safe random value. The ``else`` branch uses a small
    # positive range to avoid violating other CHECKs (e.g., remaining
    # must be <= principal). For integer VALUE2, use int; for float, use float.
    # RANGE AWARENESS: if the column also has a range CHECK constraint
    # (e.g., ``col >= 0.0 AND col <= 1.0``), the random branch must
    # respect those bounds instead of the hardcoded [0.01, 100.0].
    # This prevents CHECK violations when the column's allowed range is
    # narrower than the default. e.g., discount_rate has range [0.0, 1.0]
    # and Pattern 31 constraint ``status != 'trialing' OR discount_rate = 0.0``;
    # the else branch must use random_float(0.01, 1.0), not 100.0.
    m = re.match(
        rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    other_col_p31, val_str_p31, eq_val_str = m.group(1), m.group(2), m.group(3)
    if other_col_p31 not in col_set or other_col_p31 == col_name:
        return None
    is_float_p31 = "." in eq_val_str
    eq_val: float | int = float(eq_val_str) if is_float_p31 else int(eq_val_str)
    # Scan all constraints for a range CHECK on this column:
    # ``col >= X AND col <= Y`` or ``col >= X`` / ``col <= Y`` (separate)
    range_min, range_max = _find_equality_fallback_bounds(context)
    rand_expr = _equality_random_expression(is_float_p31, range_min, range_max)
    return {
        "derive_from": other_col_p31,
        "expression": f"{eq_val} if value == '{val_str_p31}' else {rand_expr}",
    }


def _equality_random_expression(is_float: bool, range_min: float | None, range_max: float | None) -> str:
    # Build rand_expr using range bounds if available
    if is_float:
        lo = max(0.01, range_min) if range_min is not None else 0.01
        hi = min(100.0, range_max) if range_max is not None else 100.0
        if lo > hi:
            lo, hi = hi, lo
        rand_expr = f"random_float({lo}, {hi})"
    else:
        lo_i = max(1, int(range_min)) if range_min is not None else 1
        hi_i = min(100, int(range_max)) if range_max is not None else 100
        if lo_i > hi_i:
            lo_i, hi_i = hi_i, lo_i
        rand_expr = f"random_int({lo_i}, {hi_i})"
    return rand_expr


def _match_bounded_multiplier(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 22b: col >= X AND col <= col2 * CONSTANT (compound range
    # with multiplier upper bound)
    # e.g., fee >= 0.0 AND fee <= amount * 0.02
    # e.g., tax >= 0.0 AND tax <= subtotal * 0.08
    # Derive from col2, multiply by a random factor in [0, CONSTANT] to
    # guarantee col <= col2 * CONSTANT. The lower bound X is satisfied
    # by using max(X, ...) in the expression.
    m = re.match(
        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        x_str_p22b, other_col_p22b, c_str_p22b = m.group(1), m.group(2), m.group(3)
        if other_col_p22b in col_set and other_col_p22b != col_name:
            x_val_p22b = float(x_str_p22b) if "." in x_str_p22b else int(x_str_p22b)
            c_val_p22b = float(c_str_p22b)
            # Generate value * random_factor where random_factor ∈ [0, c_val]
            # This guarantees col <= col2 * c_val. The lower bound X is
            # satisfied because value * 0 = 0 >= X when X <= 0 (common case).
            # For X > 0, use max(X, ...) to enforce the lower bound.
            if x_val_p22b <= 0:
                return {
                    "derive_from": other_col_p22b,
                    "expression": f"value * random_float(0.0, {c_val_p22b})",
                }
            # X > 0: need to ensure col >= X. Use max(X, value * factor).
            return {
                "derive_from": other_col_p22b,
                "expression": f"max({x_val_p22b}, value * random_float(0.0, {c_val_p22b}))",
            }
    return None


def _match_conditional_positive_or_null(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 32: (col1 = VALUE AND col > X) OR (col1 IN (...) AND col IS NULL)
    # (conditional value/NULL — col must be > X when col1 == VALUE,
    # and must be NULL when col1 is in the other set)
    # e.g., (card_type = 'credit' AND credit_limit > 0.0)
    #       OR (card_type IN ('debit', 'prepaid') AND credit_limit IS NULL)
    # Derive from col1: when col1 == VALUE, set col to a positive random;
    # when col1 IN other set, set col to None.
    m = re.match(
        rf"^\s*\(\s*(\w+)\s*=\s*'([^']+)'\s+AND\s+{col}\s*>\s*(-?\d+(?:\.\d+)?)\s*\)"
        rf"\s*OR\s*\(\s*\1\s+IN\s*\(([^)]+)\)\s+AND\s+{col}\s+IS\s+NULL\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        other_col_p32, val_str_p32, threshold_str_p32, values_str_p32 = (
            m.group(1),
            m.group(2),
            m.group(3),
            m.group(4),
        )
        if other_col_p32 in col_set and other_col_p32 != col_name:
            threshold_p32 = float(threshold_str_p32)
            if not (values_p32 := re.findall(_SINGLE_QUOTED_VALUE, values_str_p32)):
                values_p32 = re.findall(_DOUBLE_QUOTED_VALUE, values_str_p32)
            if values_p32:
                py_list_p32 = "[" + ", ".join(f"'{v}'" for v in values_p32) + "]"
                # When col1 == VALUE: col = random positive (> threshold)
                # When col1 IN other set: col = None (NULL)
                positive_expr_p32 = f"random_float({threshold_p32 + 0.01}, {threshold_p32 + 10000.0})"
                null_branch = f"None if value in {py_list_p32} else {positive_expr_p32}"
                return {
                    "derive_from": other_col_p32,
                    "expression": f"({positive_expr_p32}) if value == '{val_str_p32}' else ({null_branch})",
                }
    return None


def _match_conditional_arithmetic(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 33: (col1 IN (...) AND col = col2 + col3) OR (col1 IN (...) AND col = col2 - col3)
    # (conditional arithmetic based on type — col is computed differently
    # depending on col1's value)
    # e.g., (type IN ('deposit', 'transfer_in', 'interest') AND balance_after = balance_before + amount)
    #       OR (type IN ('withdrawal', 'transfer_out', 'fee') AND balance_after = balance_before - amount)
    # Derive from col2 (the base value), reference col1 (type) and col3 (amount) via row dict.
    m = re.match(
        rf"^\s*\(\s*(\w+)\s+IN\s*\(([^)]+)\)\s+AND\s+{col}\s*=\s*(\w+)\s*([+\-])\s*(\w+)\s*\)"
        rf"\s*OR\s*\(\s*\1\s+IN\s*\(([^)]+)\)\s+AND\s+{col}\s*=\s*\3\s*([+\-])\s*\5\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        type_col_p33, set1_str, base_col_p33, op1_p33, amt_col_p33, _set2_str, op2_p33 = (
            m.group(1),
            m.group(2),
            m.group(3),
            m.group(4),
            m.group(5),
            m.group(6),
            m.group(7),
        )
        if type_col_p33 in col_set and base_col_p33 in col_set and amt_col_p33 in col_set and base_col_p33 != col_name:
            if not (set1_vals := re.findall(_SINGLE_QUOTED_VALUE, set1_str)):
                set1_vals = re.findall(_DOUBLE_QUOTED_VALUE, set1_str)
            if set1_vals:
                py_list1_p33 = "[" + ", ".join(f"'{v}'" for v in set1_vals) + "]"
                # When type IN set1: col = base + amount (op1)
                # When type IN set2: col = base - amount (op2)
                expr_p33 = (
                    f"(value {op1_p33} row['{amt_col_p33}']) if row['{type_col_p33}'] in {py_list1_p33} "
                    f"else (value {op2_p33} row['{amt_col_p33}'])"
                )
                return {
                    "derive_from": base_col_p33,
                    "expression": expr_p33,
                }
    return None


def _match_conditional_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    constraints = context.constraints
    all_columns = context.all_columns
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 34: col1 != VALUE OR col2 < X (conditional upper bound)
    # e.g., status != 'dormant' OR balance < 100.0
    # When col1 != VALUE: col2 must be < X (exclusive upper bound)
    # When col1 == VALUE: col2 can be anything (no upper restriction)
    # Safe approach: set max_value to X - epsilon unconditionally. This is
    # more restrictive than necessary for the VALUE case (dormant accounts
    # could have balance >= 100.0), but satisfies ALL CHECKs. The single-
    # column lower bound (if any) is preserved by calling
    # ``_infer_from_check_constraints`` to recover min_value (e.g.,
    # ``balance >= -10000.0``).
    # Also handles ``col1 != VALUE OR col2 <= X`` (inclusive upper bound).
    m = re.match(
        rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*(<|<=)\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    other_col_p34, _val_str_p34, op_p34, x_str_p34 = (
        m.group(1),
        m.group(2),
        m.group(3),
        m.group(4),
    )
    if other_col_p34 not in col_set or other_col_p34 == col_name:
        return None
    is_float_p34 = "." in x_str_p34
    x_val_p34 = float(x_str_p34)
    # Get single-column params (e.g., min_value from `balance >= -10000.0`)
    # to preserve the lower bound that would otherwise be lost when
    # cross-column inference overrides single-column inference.
    single_p34 = _infer_from_check_constraints(col_name, constraints, all_columns)
    if op_p34 == "<":
        # Exclusive: max must be < X, so set max_value = X - epsilon
        if is_float_p34:
            params_p34: dict[str, Any] = {"max_value": x_val_p34 - 0.01}
            gen_p34 = "float"
        else:
            params_p34 = {"max_value": int(x_val_p34) - 1}
            gen_p34 = "integer"
    elif is_float_p34:
        # Inclusive: max can be = X, so set max_value = X
        params_p34 = {"max_value": x_val_p34}
        gen_p34 = "float"
    else:
        params_p34 = {"max_value": int(x_val_p34)}
        gen_p34 = "integer"
    # Merge single-column lower bound if available
    if single_p34 and single_p34[1].get("min_value") is not None:
        params_p34["min_value"] = single_p34[1]["min_value"]
    return {"generator": gen_p34, "params": params_p34}


def _match_conditional_integer_upper(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    constraints = context.constraints
    all_columns = context.all_columns
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 34b: col1 != INTEGER_VALUE OR col (<|<=) X
    # (integer-value variant of Pattern 34 — VALUE is an unquoted integer)
    # e.g., is_system != 1 OR priority < 100
    # Same semantics as Pattern 34: set max_value to X - epsilon
    # (exclusive) or X (inclusive) unconditionally. Preserves single-column
    # lower bound via _infer_from_check_constraints.
    m = re.match(
        rf"^\s*(\w+)\s*!=\s*(-?\d+)\s+OR\s+{col}\s*(<|<=)\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    other_col_p34b, _val_str_p34b, op_p34b, x_str_p34b = (
        m.group(1),
        m.group(2),
        m.group(3),
        m.group(4),
    )
    if other_col_p34b not in col_set or other_col_p34b == col_name:
        return None
    is_float_p34b = "." in x_str_p34b
    x_val_p34b = float(x_str_p34b)
    single_p34b = _infer_from_check_constraints(col_name, constraints, all_columns)
    if op_p34b == "<":
        if is_float_p34b:
            params_p34b: dict[str, Any] = {"max_value": x_val_p34b - 0.01}
            gen_p34b = "float"
        else:
            params_p34b = {"max_value": int(x_val_p34b) - 1}
            gen_p34b = "integer"
    elif is_float_p34b:
        params_p34b = {"max_value": x_val_p34b}
        gen_p34b = "float"
    else:
        params_p34b = {"max_value": int(x_val_p34b)}
        gen_p34b = "integer"
    if single_p34b and single_p34b[1].get("min_value") is not None:
        params_p34b["min_value"] = single_p34b[1]["min_value"]
    return {"generator": gen_p34b, "params": params_p34b}


def _match_conditional_integer_positive(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 28b: col1 != INTEGER_VALUE OR col > X
    # (integer-value variant of Pattern 28 — VALUE is an unquoted integer)
    # e.g., is_approved != 1 OR approved_count > 0
    # Same semantics as Pattern 28: derive from col1; when col1 == VALUE,
    # produce a value > threshold; otherwise produce 0.
    m = re.match(
        rf"^\s*(\w+)\s*!=\s*(-?\d+)\s+OR\s+{col}\s*>\s*(-?[0-9]+(?:\.[0-9]+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        other_col_p28b, val_str_p28b, threshold_str_p28b = (
            m.group(1),
            m.group(2),
            m.group(3),
        )
        if other_col_p28b in col_set and other_col_p28b != col_name:
            threshold_p28b = float(threshold_str_p28b)
            val_int_p28b = int(val_str_p28b)
            positive_expr_p28b = f"random_float({threshold_p28b + 0.01}, {threshold_p28b + 100.0})"
            zero_expr_p28b = "0.0" if is_float_type else "0"
            return {
                "derive_from": other_col_p28b,
                "expression": (f"{positive_expr_p28b} if value == {val_int_p28b} else {zero_expr_p28b}"),
            }
    return None


def _match_literal_or_threshold(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    expr = c.get("expression", "")
    # Pattern 28c: col = NUMERIC_VALUE OR other_col (>|>=|<|<=) threshold
    # (equality-first variant of Pattern 28 — col is compared with
    # equality against a numeric VALUE, and other_col is compared with
    # an inequality against a literal threshold)
    # e.g., overage_charge = 0.0 OR overage_amount > 0.0
    # Semantics: when other_col does NOT satisfy the comparison (e.g.,
    # other_col <= threshold for ``>``), col must be VALUE. When
    # other_col satisfies the comparison, col can be anything.
    # Derive from other_col: when the comparison fails, set col = VALUE;
    # otherwise set col to a random value (could be VALUE or non-VALUE,
    # both satisfy the CHECK because the second OR branch is true).
    m = re.match(
        rf"^\s*{col}\s*=\s*(-?\d+(?:\.\d+)?)\s+OR\s+(\w+)\s*(>=|>|<=|<)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    val_str_p28c, other_col_p28c, op_p28c, threshold_str_p28c = (
        m.group(1),
        m.group(2),
        m.group(3),
        m.group(4),
    )
    if other_col_p28c not in col_set or other_col_p28c == col_name:
        return None
    is_float_p28c = "." in val_str_p28c or "." in threshold_str_p28c
    val_num_p28c: float | int = float(val_str_p28c) if "." in val_str_p28c else int(val_str_p28c)
    threshold_p28c = float(threshold_str_p28c)
    # Build the "comparison NOT satisfied" condition — when this
    # is true, col must be VALUE (first OR branch is the only way
    # to satisfy the CHECK).
    if op_p28c == ">":
        fail_cond_p28c = f"value <= {threshold_p28c}"
    elif op_p28c == ">=":
        fail_cond_p28c = f"value < {threshold_p28c}"
    elif op_p28c == "<":
        fail_cond_p28c = f"value >= {threshold_p28c}"
    else:  # <=
        fail_cond_p28c = f"value > {threshold_p28c}"
    # When comparison is satisfied, col can be any value (use a
    # random value in a reasonable range; VALUE itself also
    # satisfies the CHECK via the first OR branch, so the random
    # range can include VALUE).
    random_expr_p28c = "random_float(0.0, 100.0)" if is_float_p28c else "random_int(0, 100)"
    return {
        "derive_from": other_col_p28c,
        "expression": f"{val_num_p28c} if {fail_cond_p28c} else {random_expr_p28c}",
    }


def _match_enum_or_null(context: _CrossColumnContext, c: dict[str, Any]) -> dict[str, Any] | None:
    col_name = context.col_name
    col = context.col
    col_set = context.col_set
    is_date_col = context.is_date_col
    is_float_type = context.is_float_type
    expr = c.get("expression", "")
    # Pattern 35: col1 IN (...) OR col IS NULL (conditional NULL with IN set)
    # e.g., status IN ('completed') OR completed_at IS NULL
    # When col1 IN set: col can be anything
    # When col1 NOT IN set: col must be NULL
    # For date columns: return null_ratio=1.0 (always NULL). This is the
    # safest approach — it satisfies both this CHECK and any
    # ``col IS NULL OR col > other`` CHECK that might also exist. The
    # trade-off is that the column is always NULL (semantically suboptimal
    # but functionally correct). The LLM can improve this later.
    # For non-date columns: derive from col1, return None when NOT in set.
    m = re.match(
        rf"^\s*(\w+)\s+IN\s*\(([^)]+)\)\s+OR\s+{col}\s+IS\s+NULL\s*$",
        expr,
        re.IGNORECASE,
    )
    if not m:
        return None
    other_col_p35, values_str_p35 = m.group(1), m.group(2)
    if other_col_p35 not in col_set or other_col_p35 == col_name:
        return None
    if is_date_col:
        # Always NULL — satisfies both Pattern 35 and Pattern 1
        return {"generator": "datetime", "params": {}, "null_ratio": 1.0}
    # Non-date: derive from col1, None when not in set
    if not (values_p35 := re.findall(_SINGLE_QUOTED_VALUE, values_str_p35)):
        values_p35 = re.findall(_DOUBLE_QUOTED_VALUE, values_str_p35)
    if not values_p35:
        return None
    py_list_p35 = "[" + ", ".join(f"'{v}'" for v in values_p35) + "]"
    non_null_expr_p35 = "0.0" if is_float_type else "0"
    return {
        "derive_from": other_col_p35,
        "expression": f"{non_null_expr_p35} if value in {py_list_p35} else None",
    }


def _find_conditional_null_sibling(context: _CrossColumnContext) -> tuple[str | None, str | None, str | None]:
    col = context.col
    col_name = context.col_name
    col_set = context.col_set
    constraints = context.constraints
    p30_other_col: str | None = None
    p30_val_str: str | None = None
    p30_sibling_col: str | None = None
    for c_p30 in constraints:
        if c_p30.get("type") != "check":
            continue
        expr_p30 = c_p30.get("expression", "")
        m_p30 = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s+IS\s+NULL\s*$",
            expr_p30,
            re.IGNORECASE,
        )
        if m_p30:
            p30_other_col = m_p30.group(1)
            p30_val_str = m_p30.group(2)
            if p30_other_col not in col_set or p30_other_col == col_name:
                p30_other_col = None
                continue
            # Scan for sibling Pattern 1: col IS NULL OR col (>=|>) other_col2
            p30_sibling_col = _find_nullable_ordering_source(context)
            break
    return p30_other_col, p30_val_str, p30_sibling_col


def _find_nullable_ordering_source(context: _CrossColumnContext) -> str | None:
    col = context.col
    col_name = context.col_name
    col_set = context.col_set
    constraints = context.constraints
    for c_p30sib in constraints:
        if c_p30sib.get("type") != "check":
            continue
        expr_p30sib = c_p30sib.get("expression", "")
        m_p30sib = re.match(
            rf"^\s*{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>)\s*(\w+)\s*$",
            expr_p30sib,
            re.IGNORECASE,
        )
        if m_p30sib:
            sib_col = m_p30sib.group(2)
            if sib_col in col_set and sib_col != col_name:
                return sib_col
    return None


def _build_conditional_priority_range(
    context: _CrossColumnContext, other_col_p27_pre: str, clauses_p27_pre: list[tuple[str, str, str, str]]
) -> dict[str, Any] | None:
    all_columns = context.all_columns
    col_name = context.col_name
    constraints = context.constraints
    parts_p27_pre: list[str] = []
    for _other, vi, opi, xi in clauses_p27_pre[:-1]:
        xi_num = float(xi)
        rand_expr = _range_expr_for_op(opi, xi_num)
        parts_p27_pre.append(f"{rand_expr} if value == '{vi}'")
    _other, _last_vi, last_op, last_xi = clauses_p27_pre[-1]
    last_rand = _range_expr_for_op(last_op, float(last_xi))
    expr_chain = last_rand
    for idx in range(len(parts_p27_pre) - 1, -1, -1):
        expr_chain = f"{parts_p27_pre[idx]} else ({expr_chain})"
    # Apply column-level CHECK bounds (min/max) as wrappers.
    # Pattern 27 clause ranges (e.g., ``>= 100`` →
    # ``random_float(100, 200)``) may exceed the column's
    # single-column CHECK (e.g., ``<= 100``). Wrap with
    # ``min(result, max_val)`` / ``max(result, min_val)`` to
    # enforce both Pattern 27 clause ranges AND column-level
    # bounds simultaneously. ``min``/``max`` are in SAFE_FUNCTIONS.
    if (col_check := _infer_from_check_constraints(col_name, constraints, all_columns)) is not None:
        _ck_gen, ck_params = col_check
        max_val = ck_params.get("max_value")
        min_val = ck_params.get("min_value")
        if max_val is not None:
            expr_chain = f"min({expr_chain}, {max_val})"
        if min_val is not None:
            expr_chain = f"max({expr_chain}, {min_val})"
    return {
        "derive_from": other_col_p27_pre,
        "expression": expr_chain,
    }


def _find_nullable_lower_column(context: _CrossColumnContext) -> str | None:
    col = context.col
    col_name = context.col_name
    col_set = context.col_set
    constraints = context.constraints
    lower_bound_col_p1b: str | None = None
    for lc_p1b in constraints:
        if lc_p1b.get("type") != "check":
            continue
        lc_expr_p1b = lc_p1b.get("expression", "")
        m_low_p1b = re.match(
            rf"^\s*{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>)\s*(\w+)\s*$",
            lc_expr_p1b,
            re.IGNORECASE,
        )
        if m_low_p1b:
            lb_col_p1b = m_low_p1b.group(2)
            if lb_col_p1b in col_set and lb_col_p1b != col_name:
                lower_bound_col_p1b = lb_col_p1b
                break
    return lower_bound_col_p1b


def _find_nullable_literal_bounds(context: _CrossColumnContext) -> tuple[float | None, float | None]:
    col = context.col
    constraints = context.constraints
    lower_bound_literal_p1b: float | None = None
    upper_bound_literal_p1b: float | None = None
    for bc_p1b in constraints:
        if bc_p1b.get("type") != "check":
            continue
        bc_expr_p1b = bc_p1b.get("expression", "")
        m_low_lit = re.match(
            rf"^\s*{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>)\s*(-?\d+(?:\.\d+)?)\s*$",
            bc_expr_p1b,
            re.IGNORECASE,
        )
        if m_low_lit and lower_bound_literal_p1b is None:
            lower_bound_literal_p1b = float(m_low_lit.group(2))
        m_up_lit = re.match(
            rf"^\s*{col}\s+IS\s+NULL\s+OR\s+{col}\s*(<=|<)\s*(-?\d+(?:\.\d+)?)\s*$",
            bc_expr_p1b,
            re.IGNORECASE,
        )
        if m_up_lit and upper_bound_literal_p1b is None:
            upper_bound_literal_p1b = float(m_up_lit.group(2))
    return lower_bound_literal_p1b, upper_bound_literal_p1b


def _match_bounded_nullable_three_way(
    context: _CrossColumnContext, c: dict[str, Any], bounds: _NullableComparisonBounds
) -> dict[str, Any] | None:
    col = context.col
    col_name = context.col_name
    col_set = context.col_set
    if c.get("type") != "check":
        return None
    expr_p1b = c.get("expression", "")
    if not re.search(rf"\b{col}\b", expr_p1b, re.IGNORECASE):
        return None
    m_p1b = re.search(
        rf"{col}\s+IS\s+NULL\s+OR\s+(\w+)\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
        expr_p1b,
        re.IGNORECASE,
    )
    if not m_p1b:
        # Reversed ordering: other IS NULL OR col IS NULL OR col OP other
        # e.g., temperature_min IS NULL OR temperature_max IS NULL OR temperature_max > temperature_min
        m_p1b = re.search(
            rf"(\w+)\s+IS\s+NULL\s+OR\s+{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
            expr_p1b,
            re.IGNORECASE,
        )
    if m_p1b:
        other_col_p1b_pre = m_p1b.group(1)
        op_p1b_pre = m_p1b.group(2)
        other_col_ref_p1b_pre = m_p1b.group(3)
        if (
            other_col_p1b_pre == other_col_ref_p1b_pre
            and other_col_p1b_pre in col_set
            and other_col_p1b_pre != col_name
        ):
            return _build_bounded_nullable_comparison(context, other_col_p1b_pre, op_p1b_pre, bounds)
    return None


@dataclass(frozen=True)
class _NullableComparisonBounds:
    lower_column: str | None
    lower_literal: float | None
    upper_literal: float | None


def _build_bounded_nullable_comparison(
    context: _CrossColumnContext, other_col_p1b_pre: str, op_p1b_pre: str, bounds: _NullableComparisonBounds
) -> dict[str, Any]:
    if context.is_date_col or _is_date_column(other_col_p1b_pre):
        return _bounded_nullable_date(other_col_p1b_pre, op_p1b_pre, bounds)
    if context.is_float_type:
        return _bounded_nullable_float(other_col_p1b_pre, op_p1b_pre, bounds)
    return _bounded_nullable_integer(other_col_p1b_pre, op_p1b_pre, bounds)


def _find_nullable_ordering_bounds(context: _CrossColumnContext) -> tuple[float | int | None, float | int | None]:
    col = context.col
    constraints = context.constraints
    p1_lower: float | int | None = None
    p1_upper: float | int | None = None
    for rc_p1 in constraints:
        if rc_p1.get("type") != "check":
            continue
        rc_expr_p1 = rc_p1.get("expression", "")
        # Match: col IS NULL OR (col >= X AND col <= Y)
        m_range_p1 = re.match(
            rf"^\s*{col}\s+IS\s+NULL\s+OR\s*\(\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)"
            rf"\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*\)\s*$",
            rc_expr_p1,
            re.IGNORECASE,
        )
        if not m_range_p1:
            # Also match: col >= X AND col <= Y (without IS NULL prefix)
            m_range_p1 = re.match(
                rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
                rc_expr_p1,
                re.IGNORECASE,
            )
        if m_range_p1:
            low_str_p1 = m_range_p1.group(1)
            high_str_p1 = m_range_p1.group(2)
            if "." in low_str_p1 or "." in high_str_p1:
                p1_lower = float(low_str_p1)
                p1_upper = float(high_str_p1)
            else:
                p1_lower = int(low_str_p1)
                p1_upper = int(high_str_p1)
            break
    return p1_lower, p1_upper


def _collect_conditional_numeric_branches(
    context: _CrossColumnContext,
) -> tuple[str | None, list[tuple[str, str, float, bool]]]:
    col = context.col
    col_name = context.col_name
    col_set = context.col_set
    constraints = context.constraints
    p37_branches: list[tuple[str, str, float, bool]] = []
    p37_other_col: str | None = None
    for c_p37 in constraints:
        if c_p37.get("type") != "check":
            continue
        if not (expr_p37 := c_p37.get("expression", "")):
            continue
        m_p37 = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*(>=|<=|>|<|!=)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*$",
            expr_p37,
            re.IGNORECASE,
        )
        if not m_p37:
            continue
        other_p37, val_p37, op_p37, x_str_p37 = (
            m_p37.group(1),
            m_p37.group(2),
            m_p37.group(3),
            m_p37.group(4),
        )
        # All branches must reference the same enum column
        if other_p37 not in col_set or other_p37 == col_name:
            continue
        if p37_other_col is None:
            p37_other_col = other_p37
        elif p37_other_col != other_p37:
            continue
        x_val_p37 = float(x_str_p37)
        is_float_p37 = "." in x_str_p37
        p37_branches.append((val_p37, op_p37, x_val_p37, is_float_p37))
    return p37_other_col, p37_branches


def _conditional_numeric_branch(use_float: bool, op_p37: str, x_p37: float) -> str:
    if use_float:
        if op_p37 == ">":
            branch = f"random_float({x_p37 + 0.01}, {x_p37 + 100.0})"
        elif op_p37 == ">=":
            branch = f"random_float({x_p37}, {x_p37 + 100.0})"
        elif op_p37 == "<":
            branch = f"random_float({x_p37 - 100.0}, {x_p37 - 0.01})"
        elif op_p37 == "<=":
            branch = f"random_float({x_p37 - 100.0}, {x_p37})"
        else:  # !=
            # Non-X value: alternate positive and negative ranges
            pos = f"random_float({x_p37 + 0.01}, {x_p37 + 100.0})"
            neg = f"random_float({x_p37 - 100.0}, {x_p37 - 0.01})"
            branch = f"({pos} if random_int(0, 1) == 0 else {neg})"
    else:
        x_int_p37 = int(x_p37)
        if op_p37 == ">":
            branch = f"random_int({x_int_p37 + 1}, {x_int_p37 + 100})"
        elif op_p37 == ">=":
            branch = f"random_int({x_int_p37}, {x_int_p37 + 100})"
        elif op_p37 == "<":
            branch = f"random_int({x_int_p37 - 100}, {x_int_p37 - 1})"
        elif op_p37 == "<=":
            branch = f"random_int({x_int_p37 - 100}, {x_int_p37})"
        else:  # !=
            # Non-X value: alternate positive and negative ranges
            pos = f"random_int({x_int_p37 + 1}, {x_int_p37 + 100})"
            neg = f"random_int({x_int_p37 - 100}, {x_int_p37 - 1})"
            branch = f"({pos} if random_int(0, 1) == 0 else {neg})"
    return branch


def _find_equality_fallback_bounds(context: _CrossColumnContext) -> tuple[float | None, float | None]:
    col = context.col
    constraints = context.constraints
    range_min: float | None = None
    range_max: float | None = None
    for rc in constraints:
        if rc.get("type") != "check":
            continue
        rc_expr = rc.get("expression", "")
        # Combined: col >= X AND col <= Y
        m_combined = re.match(
            rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
            rc_expr,
            re.IGNORECASE,
        )
        if m_combined:
            range_min = float(m_combined.group(1))
            range_max = float(m_combined.group(2))
            break
        # Separate lower: col >= X
        if m_low := re.match(rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s*$", rc_expr, re.IGNORECASE):
            range_min = float(m_low.group(1))
        # Separate upper: col <= Y
        if m_up := re.match(rf"^\s*{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$", rc_expr, re.IGNORECASE):
            range_max = float(m_up.group(1))
    return range_min, range_max


def _build_inequality_enum_rotation(context: _CrossColumnContext, other_col_p6: str) -> dict[str, Any] | None:
    col = context.col
    constraints = context.constraints
    for ic in constraints:
        if ic.get("type") != "check":
            continue
        ic_expr = ic.get("expression", "")
        m_in_p6 = re.match(
            rf"^\s*{col}\s+IN\s*\(([^)]+)\)\s*$",
            ic_expr,
            re.IGNORECASE,
        )
        if m_in_p6:
            in_values_p6 = re.findall(r"'([^']+)'", m_in_p6.group(1))
            if len(in_values_p6) >= 2:
                # Build chained ternary: v1→v2, v2→v3, ..., vN→v1
                parts_p6 = []
                for i_p6 in range(len(in_values_p6) - 1):
                    parts_p6.append(f"'{in_values_p6[i_p6 + 1]}' if value == '{in_values_p6[i_p6]}'")
                expr_p6 = " else ".join(parts_p6)
                expr_p6 += f" else '{in_values_p6[0]}'"
                return {
                    "derive_from": other_col_p6,
                    "expression": expr_p6,
                }
            break
    return None


def _minimum_date_comparison_days(context: _CrossColumnContext, c: dict[str, Any], other_col_p41: str) -> int:
    col = context.col
    col_type = context.col_type
    column_types = context.column_types
    constraints = context.constraints
    min_days_p41 = 1
    for c_p41 in constraints:
        if c_p41 is c or c_p41.get("type") != "check":
            continue
        expr_p41_diff = c_p41.get("expression", "")
        m_p41_diff = re.search(
            rf"(?:julianday\()?{col}\)?\s*-\s*(?:julianday\()?{other_col_p41}\)?\s*(>=|>)\s*(\d+)",
            expr_p41_diff,
            re.IGNORECASE,
        )
        if m_p41_diff:
            diff_op = m_p41_diff.group(1)
            diff_n = int(m_p41_diff.group(2))
            if (bound := diff_n if diff_op == ">=" else diff_n + 1) > min_days_p41:
                min_days_p41 = bound
    # DATE-vs-DATETIME compensation: when the target column
    # is DATE-only (no time component) and the source column
    # is DATETIME (has time component), the stored target
    # value loses its time component (set to midnight),
    # while the source retains its time. This causes the
    # julianday diff to be ``N - time_fraction``, which can
    # drop below the threshold ``N`` when random_int returns
    # exactly N. Add 1 extra day to guarantee the constraint
    # is always satisfied.
    # e.g., maturity_date (DATE) derives from disbursed_at
    # (DATETIME): ``julianday(maturity_date) -
    # julianday(disbursed_at) >= 30`` — without +1, when
    # random_int(30, 365) returns 30, the diff is
    # ``30 - 0.766 = 29.234 < 30`` → CHECK fails.
    target_is_date_only = _is_date_only_type(col_type)
    source_is_datetime = column_types is not None and _is_datetime_type(column_types.get(other_col_p41, ""))
    if target_is_date_only and source_is_datetime:
        min_days_p41 += 1
    return min_days_p41


def _bounded_nullable_date(
    other_col_p1b_pre: str, op_p1b_pre: str, bounds: _NullableComparisonBounds
) -> dict[str, Any]:
    lower_bound_col_p1b = bounds.lower_column
    if op_p1b_pre in {">=", ">"}:
        return {
            "derive_from": other_col_p1b_pre,
            "expression": "None if value is None else value + timedelta(days=random_int(1, 365))",
        }
    days_p1b_pre = "0" if op_p1b_pre == "<=" else "1"
    inner_p1b = f"value - timedelta(days=random_int({days_p1b_pre}, 365))"
    if lower_bound_col_p1b:
        inner_p1b = f"max({inner_p1b}, row['{lower_bound_col_p1b}'])"
    return {
        "derive_from": other_col_p1b_pre,
        "expression": f"None if value is None else {inner_p1b}",
    }


def _bounded_nullable_float(
    other_col_p1b_pre: str, op_p1b_pre: str, bounds: _NullableComparisonBounds
) -> dict[str, Any]:
    lower_bound_col_p1b = bounds.lower_column
    lower_bound_literal_p1b = bounds.lower_literal
    upper_bound_literal_p1b = bounds.upper_literal
    if op_p1b_pre == ">=":
        inner_p1b_ge = "value + random_float(0, 100)"
        if upper_bound_literal_p1b is not None:
            inner_p1b_ge = f"min({inner_p1b_ge}, {upper_bound_literal_p1b})"
        return {
            "derive_from": other_col_p1b_pre,
            "expression": f"None if value is None else {inner_p1b_ge}",
        }
    if op_p1b_pre == ">":
        # Addition (not multiplication) ensures result > value for
        # ALL signs of value. ``value * 1.01`` makes negative values
        # MORE negative (e.g., -20.0 * 1.01 = -20.2 < -20.0), violating
        # ``col > other_col``. ``value + delta`` (delta > 0) is
        # sign-agnostic and always satisfies the strict inequality.
        inner_p1b_gt = _FLOAT_ABOVE_SOURCE
        if upper_bound_literal_p1b is not None:
            # When ``value >= upper_bound``, the constraint
            # ``col > value AND col <= upper_bound`` is unsolvable
            # (no number is simultaneously > value and <= upper_bound
            # when value >= upper_bound) → return None (NULL).
            # Otherwise, min() caps the result to upper_bound, which
            # is still > value since value < upper_bound.
            inner_p1b_gt = (
                f"None if value >= {upper_bound_literal_p1b} else min({inner_p1b_gt}, {upper_bound_literal_p1b})"
            )
        return {
            "derive_from": other_col_p1b_pre,
            "expression": f"None if value is None else {inner_p1b_gt}",
        }
    if op_p1b_pre == "<=":
        # Subtraction ensures result <= value for ALL signs.
        # ``value * 0.5`` for negative values produces a LARGER value
        # (e.g., -20.0 * 0.5 = -10.0 > -20.0), violating ``col <= other_col``.
        # ``value - delta`` (delta >= 0) is sign-agnostic.
        inner_p1b_f = "value - random_float(0, 100)"
        if lower_bound_col_p1b:
            inner_p1b_f = f"max({inner_p1b_f}, row['{lower_bound_col_p1b}'])"
        if lower_bound_literal_p1b is not None:
            inner_p1b_f = f"max({inner_p1b_f}, {lower_bound_literal_p1b})"
        return {
            "derive_from": other_col_p1b_pre,
            "expression": f"None if value is None else {inner_p1b_f}",
        }
    # op_p1b_pre == "<" — strict less-than
    inner_p1b_f_lt = _FLOAT_BELOW_SOURCE
    if lower_bound_col_p1b:
        inner_p1b_f_lt = f"max({inner_p1b_f_lt}, row['{lower_bound_col_p1b}'])"
    if lower_bound_literal_p1b is not None:
        inner_p1b_f_lt = f"max({inner_p1b_f_lt}, {lower_bound_literal_p1b})"
    return {
        "derive_from": other_col_p1b_pre,
        "expression": f"None if value is None else {inner_p1b_f_lt}",
    }


def _bounded_nullable_integer(
    other_col_p1b_pre: str, op_p1b_pre: str, bounds: _NullableComparisonBounds
) -> dict[str, Any]:
    lower_bound_col_p1b = bounds.lower_column
    lower_bound_literal_p1b = bounds.lower_literal
    upper_bound_literal_p1b = bounds.upper_literal
    if op_p1b_pre == ">=":
        inner_p1b_ige = _INTEGER_AT_OR_ABOVE_SOURCE
        if upper_bound_literal_p1b is not None:
            inner_p1b_ige = f"min({inner_p1b_ige}, {int(upper_bound_literal_p1b)})"
        return {
            "derive_from": other_col_p1b_pre,
            "expression": f"None if value is None else {inner_p1b_ige}",
        }
    if op_p1b_pre == ">":
        inner_p1b_igt = _INTEGER_ABOVE_SOURCE
        if upper_bound_literal_p1b is not None:
            inner_p1b_igt = f"min({inner_p1b_igt}, {int(upper_bound_literal_p1b)})"
        return {
            "derive_from": other_col_p1b_pre,
            "expression": f"None if value is None else {inner_p1b_igt}",
        }
    if op_p1b_pre == "<=":
        inner_p1b_i = _INTEGER_AT_OR_BELOW_SOURCE
        if lower_bound_col_p1b:
            inner_p1b_i = f"max({inner_p1b_i}, row['{lower_bound_col_p1b}'])"
        if lower_bound_literal_p1b is not None:
            inner_p1b_i = f"max({inner_p1b_i}, {int(lower_bound_literal_p1b)})"
        return {
            "derive_from": other_col_p1b_pre,
            "expression": f"None if value is None else {inner_p1b_i}",
        }
    inner_p1b_i_lt = _INTEGER_BELOW_SOURCE
    if lower_bound_col_p1b:
        inner_p1b_i_lt = f"max({inner_p1b_i_lt}, row['{lower_bound_col_p1b}'])"
    if lower_bound_literal_p1b is not None:
        inner_p1b_i_lt = f"max({inner_p1b_i_lt}, {int(lower_bound_literal_p1b)})"
    return {
        "derive_from": other_col_p1b_pre,
        "expression": f"None if value is None else {inner_p1b_i_lt}",
    }


def _build_nullable_three_way(context: _CrossColumnContext, other_col_p1b: str, op_p1b: str) -> dict[str, Any]:
    is_date_col = context.is_date_col
    is_float_type = context.is_float_type
    if is_date_col or _is_date_column(other_col_p1b):
        if op_p1b in {">=", ">"}:
            return {
                "derive_from": other_col_p1b,
                "expression": "None if value is None else value + timedelta(days=random_int(1, 365))",
            }
        days_p1b = "0" if op_p1b == "<=" else "1"
        return {
            "derive_from": other_col_p1b,
            "expression": f"None if value is None else value - timedelta(days=random_int({days_p1b}, 365))",
        }
    return _build_numeric_nullable_three_way(other_col_p1b, op_p1b, is_float_type)


def _build_numeric_nullable_three_way(other_col_p1b: str, op_p1b: str, is_float_type: bool) -> dict[str, Any]:
    if is_float_type:
        if op_p1b == ">=":
            return {
                "derive_from": other_col_p1b,
                "expression": "None if value is None else value + random_float(0, 100)",
            }
        if op_p1b == ">":
            # Addition (not multiplication) — see pre-loop scan comment.
            # ``value * 1.01`` violates ``col > other_col`` for negative values.
            return {
                "derive_from": other_col_p1b,
                "expression": "None if value is None else value + random_float(0.01, 100.0)",
            }
        if op_p1b == "<=":
            # Subtraction — ``value * 0.5`` violates ``col <= other_col`` for negatives.
            return {
                "derive_from": other_col_p1b,
                "expression": "None if value is None else value - random_float(0, 100)",
            }
        return {
            "derive_from": other_col_p1b,
            "expression": "None if value is None else value - random_float(0.01, 100.0)",
        }
    if op_p1b == ">=":
        return {
            "derive_from": other_col_p1b,
            "expression": "None if value is None else value + random_int(0, 100)",
        }
    if op_p1b == ">":
        return {
            "derive_from": other_col_p1b,
            "expression": "None if value is None else value + random_int(1, 100)",
        }
    if op_p1b == "<=":
        return {
            "derive_from": other_col_p1b,
            "expression": "None if value is None else value - random_int(0, 100)",
        }
    return {
        "derive_from": other_col_p1b,
        "expression": "None if value is None else value - random_int(1, 100)",
    }


def _build_nullable_ordering(
    context: _CrossColumnContext, other_col: str, op: str, p1_lower: float | int | None, p1_upper: float | int | None
) -> dict[str, Any]:
    is_date_col = context.is_date_col
    is_float_type = context.is_float_type

    if is_date_col or _is_date_column(other_col):
        # Date columns: use timedelta
        return _build_nullable_date_ordering(other_col, op)
    if is_float_type:
        # Float columns: use additive offsets (NOT multiplication).
        # Multiplication ``value * factor`` only produces ``result > value``
        # when ``value > 0``; for negative values it reverses the inequality.
        # Addition/subtraction is sign-agnostic and always correct.
        if op == ">=":
            return {
                "derive_from": other_col,
                "expression": _wrap_nullable_ordering_bounds("value + random_float(0, 100)", p1_lower, p1_upper),
            }
        if op == ">":
            return {
                "derive_from": other_col,
                "expression": _wrap_nullable_ordering_bounds(_FLOAT_ABOVE_SOURCE, p1_lower, p1_upper),
            }
        if op == "<=":
            return {
                "derive_from": other_col,
                "expression": _wrap_nullable_ordering_bounds("value - random_float(0, 100)", p1_lower, p1_upper),
            }
        # op == "<"
        return {
            "derive_from": other_col,
            "expression": _wrap_nullable_ordering_bounds(_FLOAT_BELOW_SOURCE, p1_lower, p1_upper),
        }
    # Integer columns: use additive offsets
    if op == ">=":
        return {
            "derive_from": other_col,
            "expression": _wrap_nullable_ordering_bounds(_INTEGER_AT_OR_ABOVE_SOURCE, p1_lower, p1_upper),
        }
    if op == ">":
        return {
            "derive_from": other_col,
            "expression": _wrap_nullable_ordering_bounds(_INTEGER_ABOVE_SOURCE, p1_lower, p1_upper),
        }
    if op == "<=":
        return {
            "derive_from": other_col,
            "expression": _wrap_nullable_ordering_bounds(_INTEGER_AT_OR_BELOW_SOURCE, p1_lower, p1_upper),
        }
    # op == "<"
    return {
        "derive_from": other_col,
        "expression": _wrap_nullable_ordering_bounds(_INTEGER_BELOW_SOURCE, p1_lower, p1_upper),
    }


def _build_date_right_ordering(
    context: _CrossColumnContext, c: dict[str, Any], other_col_p41: str, op_p41: str
) -> dict[str, Any]:
    is_date_col = context.is_date_col
    is_float_type = context.is_float_type
    if is_date_col or _is_date_column(other_col_p41):
        if op_p41 in {">=", ">"}:
            # Scan for date-difference constraints like
            # ``col - other_col >= N`` or ``col - other_col > N``
            # which require a minimum day offset. Use the max N
            # found as the lower bound (N+1 for strict >).
            # e.g., ``maturity_date - disbursed_at >= 30`` →
            # lower bound 30 days.
            # Also matches the SQLite-compatible julianday() form:
            # ``julianday(col) - julianday(other_col) >= N``
            # (standard ISO date subtraction returns 0 in SQLite,
            # so schemas targeting SQLite should use julianday()).
            min_days_p41 = _minimum_date_comparison_days(context, c, other_col_p41)
            return {
                "derive_from": other_col_p41,
                "expression": f"value + timedelta(days=random_int({min_days_p41}, 365))",
            }
        days_p41 = "0" if op_p41 == "<=" else "1"
        return {
            "derive_from": other_col_p41,
            "expression": f"value - timedelta(days=random_int({days_p41}, 365))",
        }
    return _build_numeric_date_right_ordering(other_col_p41, op_p41, is_float_type)


def _build_numeric_date_right_ordering(other_col_p41: str, op_p41: str, is_float_type: bool) -> dict[str, Any]:
    if is_float_type:
        if op_p41 == ">=":
            return {
                "derive_from": other_col_p41,
                "expression": "value + random_float(1, 100)",
            }
        if op_p41 == ">":
            return {
                "derive_from": other_col_p41,
                "expression": "value * random_float(1.1, 2.0)",
            }
        if op_p41 == "<=":
            return {
                "derive_from": other_col_p41,
                "expression": "value * random_float(0.5, 1.0)",
            }
        return {
            "derive_from": other_col_p41,
            "expression": "value * random_float(0.5, 0.99)",
        }
    if op_p41 == ">=":
        return {
            "derive_from": other_col_p41,
            "expression": _INTEGER_ABOVE_SOURCE,
        }
    if op_p41 == ">":
        return {
            "derive_from": other_col_p41,
            "expression": _INTEGER_ABOVE_SOURCE,
        }
    if op_p41 == "<=":
        return {
            "derive_from": other_col_p41,
            "expression": _INTEGER_AT_OR_BELOW_SOURCE,
        }
    return {
        "derive_from": other_col_p41,
        "expression": _INTEGER_BELOW_SOURCE,
    }


def _build_nullable_date_ordering(other_col: str, op: str) -> dict[str, Any]:
    if op in {">=", ">"}:
        return {
            "derive_from": other_col,
            "expression": "value + timedelta(days=random_int(1, 365))",
        }
    # op in ("<=", "<") — subtract timedelta
    days = "0" if op == "<=" else "1"
    return {
        "derive_from": other_col,
        "expression": f"value - timedelta(days=random_int({days}, 365))",
    }


def _wrap_nullable_ordering_bounds(inner_expr: str, lower: float | int | None, upper: float | int | None) -> str:
    # Preserve the single-column CHECK range alongside cross-column ordering.
    if lower is not None and upper is not None:
        return f"max({lower}, min({upper}, {inner_expr}))"
    return inner_expr


def _conditional_fallback_literal(context: _CrossColumnContext, foreign_key_value: str) -> str:
    """Choose the numeric fallback without manufacturing an invalid foreign key."""
    if context.is_fk_column:
        return foreign_key_value
    return "0.0" if context.is_float_type else "0"


def _numeric_comparison_expression(op: str, is_float: bool) -> str:
    """Keep conditional numeric offsets valid on both sides of zero."""
    if op == ">":
        return _FLOAT_ABOVE_SOURCE if is_float else _INTEGER_ABOVE_SOURCE
    if op == ">=":
        return "value + random_float(0, 100.0)" if is_float else _INTEGER_AT_OR_ABOVE_SOURCE
    if op == "<":
        return _FLOAT_BELOW_SOURCE if is_float else _INTEGER_BELOW_SOURCE
    return "value - random_float(0, 100.0)" if is_float else _INTEGER_AT_OR_BELOW_SOURCE


def _dual_bound_random_expression(clause: tuple[str, ...], is_float: bool) -> str:
    """Build one conditional range using its inclusive/exclusive endpoints."""
    _other, _value, lo_op, lo_str, up_op, up_str = clause
    lo = float(lo_str)
    up = float(up_str)
    if lo_op == ">":
        lo += 0.01 if is_float else 1
    if up_op == "<":
        up -= 0.01 if is_float else 1
    return f"random_float({lo}, {up})" if is_float else f"random_int({int(lo)}, {int(up)})"
