"""Pure single-column CHECK inference and shared SQL predicates."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


def _placeholder_generator(col_type: str) -> str:
    """Pick a sensible placeholder generator based on column type."""
    t = col_type.upper()
    if any(k in t for k in ("INT", "BIGINT", "SMALLINT", "TINYINT")):
        return "integer"
    if any(k in t for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")):
        return "float"
    if any(k in t for k in ("TIMESTAMP", "DATETIME", "DATE", "TIME")):
        return "datetime"
    if "BOOLEAN" in t:
        return "boolean"
    return "string"


def _range_expr_for_op(op: str, x: float) -> str:
    """Build a ``random_float(...)`` expression that satisfies ``col OP x``.

    Used by Pattern 27 (N-way conditional range) to emit per-clause random
    expressions. The lower bound uses 0.01 (not 0) to avoid generating
    exactly 0 for columns that may have ``col > 0`` constraints elsewhere.

    Args:
        op: One of ``<=``, ``<``, ``>=``, ``>``.
        x: The numeric bound from the CHECK clause.

    Returns:
        A Python expression string like ``"random_float(0.01, 10.0)"``.
    """
    if op == "<=":
        return f"random_float(0.01, {x})"
    if op == "<":
        # Strict < — subtract epsilon so the generator never produces x.
        return f"random_float(0.01, {max(x - 0.01, 0.02)})"
    if op == ">=":
        return f"random_float({x}, {x + 100.0})"
    if op == ">":
        # Strict > — add epsilon so the generator never produces x.
        return f"random_float({x + 0.01}, {x + 100.0})"
    # Fallback (shouldn't happen — Pattern 27 only accepts the 4 ops above).
    return f"random_float(0.01, {x})"


def _is_date_column(col_name: str) -> bool:
    """Check if a column name suggests a date/time value.

    SQLite stores dates as TEXT, so column type alone is insufficient.
    This detects common date/time naming conventions:
    - ``*_at`` (created_at, paid_at, ordered_at)
    - ``*_date`` (hire_date, transfer_date)
    - ``*_time`` (start_time, end_time)
    - ``*_on`` (acted_on, published_on)
    - ``check_in`` / ``check_out``
    - ``date_*`` (date_of_birth)
    - ``dob``, ``created``, ``updated``, ``deleted``
    """
    n = col_name.lower()
    if n.endswith(("_at", "_date", "_time", "_on")):
        return True
    if "check_in" in n or "check_out" in n:
        return True
    if n in {"created", "updated", "deleted", "dob"}:
        return True
    return bool(n.startswith(("date_", "time_")))


def _is_date_only_type(col_type: str) -> bool:
    """Check if a column type is DATE-only (no time component).

    SQLite stores DATE and DATETIME both as TEXT, but the semantic
    distinction matters for derive_from expressions: when a DATE column
    derives from a DATETIME column, the time component is stripped at
    storage time, which can cause julianday diff constraints to fail
    (the diff becomes ``N - time_fraction``, dropping below the
    threshold ``N``).

    Returns True for ``DATE`` but False for ``DATETIME``, ``TIMESTAMP``,
    and ``TIME``.
    """
    t = col_type.upper()
    if "DATETIME" in t or "TIMESTAMP" in t:
        return False
    if "TIME" in t:
        return False  # TIME-only column
    return "DATE" in t


def _is_datetime_type(col_type: str) -> bool:
    """Check if a column type has a time component (DATETIME or TIMESTAMP)."""
    t = col_type.upper()
    return "DATETIME" in t or "TIMESTAMP" in t


def _like_to_regex(like_pattern: str) -> str:
    """Convert a SQL LIKE pattern to an anchored regex, preserving literal positions.

    SQL LIKE wildcards: ``_`` matches any single char, ``%`` matches zero+ chars.
    Only ``_`` (fixed-length) is supported — ``%`` must be filtered by the caller.

    Each ``_`` becomes a character class (consecutive runs grouped into ``{N}``),
    and literal characters are escaped with ``re.escape`` IN PLACE. This preserves
    the position of literals — critical for patterns like ``__:__`` (HH:MM time
    strings) where the colon must stay at index 2, not collapse to the start.

    Character class selection:
      - When the pattern contains ``:`` (time/HH:MM-style), ``[0-9]`` is used
        because time fields only allow digits — ``[A-Za-z0-9]`` would let rstr
        fill positions with letters, producing invalid values like ``Tc:aO``.
      - Otherwise ``[A-Za-z0-9]`` is used for general alphanumeric codes.

    Examples:
        ``__:__``  → ``^[0-9]{2}:[0-9]{2}$``
        ``#______`` → ``^#[A-Za-z0-9]{6}$``
        ``PROD-___`` → ``^PROD\\-[A-Za-z0-9]{3}$``
    """
    # Time-like patterns (containing ':') use digits-only — HH:MM fields never
    # contain letters. General alphanumeric patterns keep [A-Za-z0-9].
    char_class = "[0-9]" if ":" in like_pattern else "[A-Za-z0-9]"
    parts: list[str] = []
    underscore_run = 0
    for ch in like_pattern:
        if ch == "_":
            underscore_run += 1
        else:
            if underscore_run > 0:
                parts.append(f"{char_class}{{{underscore_run}}}" if underscore_run > 1 else char_class)
                underscore_run = 0
            parts.append(re.escape(ch))
    if underscore_run > 0:
        parts.append(f"{char_class}{{{underscore_run}}}" if underscore_run > 1 else char_class)
    return "^" + "".join(parts) + "$"


def _has_like_constraint(col_name: str, constraints: list[dict[str, Any]]) -> bool:
    """Check if a column has a LIKE CHECK constraint (formatted string column).

    A column with ``CHECK (col LIKE 'pattern')`` stores formatted strings
    (e.g., ``start_time LIKE '__:__'`` for "HH:MM" time strings). Such columns
    are NOT real datetimes — ``timedelta`` arithmetic on their string values
    fails at fill time with ``TypeError: can only concatenate str (not
    "datetime.timedelta") to str``.
    """
    col_re = re.escape(col_name)
    for c in constraints:
        if c.get("type") != "check":
            continue
        expr = c.get("expression", "")
        if re.search(rf"{col_re}\s+LIKE\s+", expr, re.IGNORECASE):
            return True
    return False


def _has_cross_column_check(col_name: str, constraints: list[dict[str, Any]]) -> bool:
    """Check if a column has a CHECK constraint referencing other columns.

    Used by the complex CHECK null_ratio safety net (Step 5.5) to detect
    columns that participate in cross-column conditional CHECKs (e.g.,
    ``is_normal = 0 OR test_value IS NULL OR (test_value >= ref_low AND ...)``).
    Such columns are candidates for null_ratio=1.0 when no Pattern (1-41)
    matched the complex CHECK — the ``IS NULL`` branch is the only safe
    fallback.

    Normalizes PostgreSQL CHECK expressions (strips ``::type`` casts) before
    tokenizing. SQL keywords (AND, OR, NOT, NULL, IS, IN, etc.) and numeric
    literals are excluded from the "other column" check.
    """
    for c in constraints:
        if c.get("type") != "check":
            continue
        expr = c.get("expression", "")
        if not expr:
            continue
        # Normalize PG expression (strip ::type casts)
        expr = _normalize_pg_check_expr(expr)
        # Check if this column is referenced
        if col_name not in expr:
            continue
        # Check if ANY other column is referenced (look for word tokens
        # that aren't SQL keywords or numeric literals)
        tokens = set(re.findall(r"\b[a-z_]\w*\b", expr.lower()))
        sql_keywords = {
            "and",
            "or",
            "not",
            "null",
            "is",
            "in",
            "between",
            "like",
            "case",
            "when",
            "then",
            "else",
            "end",
            "abs",
            "length",
            "date",
            "time",
            "timestamp",
            "true",
            "false",
        }
        col_refs = tokens - sql_keywords - {col_name.lower()}
        col_refs = {t for t in col_refs if not t.isdigit()}
        if col_refs:
            return True
    return False


def _get_unique_columns(constraints: list[dict[str, Any]]) -> set[str]:
    """Extract the set of column names that have a UNIQUE constraint.

    Covers both single-column and composite UNIQUE constraints. For composite
    UNIQUE, all member columns are included (individual column uniqueness is
    not guaranteed, but the template generator is still the safest default).
    """
    unique_cols: set[str] = set()
    for c in constraints:
        if c.get("type") != "unique":
            continue
        cols_list = c.get("columns") or []
        unique_cols.update(cols_list)
    return unique_cols


def _get_exact_length_check(
    col_name: str,
    constraints: list[dict[str, Any]],
) -> int | None:
    """Return N if the column has a ``LENGTH(col) = N`` CHECK constraint.

    Returns ``None`` if no such exact-length CHECK exists. Only matches the
    strict equality form — ``LENGTH(col) >= N`` or ``<= N`` are handled by
    the ``string`` generator's min_length/max_length and do not conflict
    with the unique adjuster (only exact length is at risk because the
    adjuster may increase max_length to guarantee uniqueness).
    """
    col = re.escape(col_name)
    for c in constraints:
        if c.get("type") != "check":
            continue
        expr = c.get("expression", "")
        if not expr:
            continue
        m = re.match(
            rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*=\s*(\d+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            return int(m.group(1))
    return None


def _infer_unique_column_config(
    col_name: str,
    col_type: str,
) -> dict[str, Any] | None:
    """Infer a uniqueness-guaranteeing config for a UNIQUE column.

    Returns a config dict with a ``template`` or ``email`` generator, or
    ``None`` if the column type is not text-like (numeric UNIQUE columns
    rely on the ConstraintSolver's backtracking for uniqueness).

    - Email columns (name contains "email"): ``email`` generator (Faker
      produces unique-enough emails for typical test data sizes).
    - Other text UNIQUE columns: ``template`` generator with a sequence
      pattern ``{PREFIX}-{sequence:04d}`` derived from the column name.
    """
    t = col_type.upper()
    is_text = any(k in t for k in ("VARCHAR", "TEXT", "CHAR", "CLOB"))
    if not is_text:
        return None
    if "email" in col_name.lower():
        return {"generator": "email", "params": {}}
    prefix = col_name.upper()[:8]
    return {
        "generator": "template",
        "params": {"template": f"{prefix}-{{sequence:04d}}"},
    }


def _normalize_pg_check_expr(expr: str) -> str:
    """Normalize PostgreSQL CHECK expression for regex pattern matching.

    PostgreSQL normalizes CHECK expressions in ``information_schema`` by:
    1. Adding ``::type`` casts (e.g., ``::double precision``, ``::text``)
    2. Wrapping RHS of ``=`` in outer parentheses
       (e.g., ``col = (unit_price * quantity + shipping_cost)``)
    3. Wrapping sub-expressions in comparison operators
       (e.g., ``col <= (max_size * 1.5)``)

    These transformations break the regex patterns in
    ``_infer_cross_column_config`` and ``_parse_single_column_check``.
    This function strips casts and outer parentheses to restore the
    original author-intended form.
    """
    # 1. Strip ::type casts (e.g., ::double precision, ::text, ::integer)
    #    Match :: followed by 1-2 word type name.
    expr = re.sub(r"::\w+(?:\s+\w+)?", "", expr)

    # 2. Strip outer parentheses around RHS of = comparison
    #    e.g., "delta = (abs(version_from) * abs(version_to))"
    #    → "delta = abs(version_from) * abs(version_to)"
    #    Uses balanced-paren check to avoid stripping function-call parens.
    m_eq = re.match(r"^(\s*\w+\s*=\s*)\((.+)\)\s*$", expr)
    if m_eq:
        prefix = m_eq.group(1)
        inner = m_eq.group(2)
        depth = 0
        balanced = True
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    balanced = False
                    break
        if balanced and depth == 0:
            expr = prefix + inner

    # 3. Strip parentheses around comparison RHS in compound expressions
    #    e.g., "size_mb <= (max_size * 1.5)" → "size_mb <= max_size * 1.5"
    #    Only strips one level; inner expression must have no parens.
    return re.sub(r"((?:>=|<=|!=|>|<)\s*)\(([^()]+)\)", r"\1\2", expr)


def _normalize_constraints(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of constraints with PostgreSQL-normalized expressions.

    Creates shallow copies of constraint dicts with normalized ``expression``
    fields, so the original list is not mutated.
    """
    result: list[dict[str, Any]] = []
    for c in constraints:
        if c.get("type") == "check" and c.get("expression"):
            nc = dict(c)
            nc["expression"] = _normalize_pg_check_expr(c["expression"])
            result.append(nc)
        else:
            result.append(c)
    return result


def _is_single_column_check(
    col_name: str,
    constraint: dict[str, Any],
    all_columns: list[str] | None,
) -> bool:
    """Select nonempty CHECKs mentioning this column and no sibling column."""
    if constraint.get("type") != "check":
        return False
    expr = constraint.get("expression", "")
    if not expr:
        return False
    if not re.search(rf"\b{re.escape(col_name)}\b", expr, re.IGNORECASE):
        return False
    if all_columns:
        other_columns = [other for other in all_columns if other != col_name]
        for other in other_columns:
            if re.search(rf"\b{re.escape(other)}\b", expr, re.IGNORECASE):
                return False
    return True


def _merge_check_bound(
    merged_params: dict[str, Any],
    params: dict[str, Any],
    key: str,
    lower_bound: bool,
) -> None:
    """Merge one bound, preserving the tighter lower or upper limit."""
    if key not in params:
        return
    value = params[key]
    if key not in merged_params:
        merged_params[key] = value
    elif lower_bound:
        merged_params[key] = max(merged_params[key], value)
    else:
        merged_params[key] = min(merged_params[key], value)


def _merge_single_column_bounds(
    merged_gen: str,
    merged_params: dict[str, Any],
    gen: str,
    params: dict[str, Any],
) -> str:
    """Promote integer bounds when needed, then merge numeric and length limits."""
    if gen == "float" and merged_gen == "integer":
        merged_gen = "float"
        for key in ("min_value", "max_value"):
            if key in merged_params and isinstance(merged_params[key], int):
                merged_params[key] = float(merged_params[key])
    # Preserve the original numeric-before-length merge order.
    for key in ("min_value", "max_value", "min_length", "max_length"):
        _merge_check_bound(merged_params, params, key, lower_bound=key.startswith("min_"))
    return merged_gen


def _infer_from_check_constraints(
    col_name: str,
    constraints: list[dict[str, Any]],
    all_columns: list[str] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Infer generator + params from CHECK constraints for a single column.

    Returns ``(generator_name, params)`` tuple, or ``None`` if no inference
    is possible. Handles:
    - ``col IN ('a', 'b', 'c')`` → choice generator (string enum)
    - ``col IN (0, 1)`` → boolean generator
    - ``col IN (1, 2, 3)`` → choice generator (numeric enum)
    - ``col >= X AND col <= Y`` → integer/float with min_value/max_value
    - ``col > X AND col < Y`` → integer/float with exclusive bounds
    - ``col >= X`` / ``col > X`` → integer/float with min_value
    - ``col <= Y`` / ``col < Y`` → integer/float with max_value

    Cross-column constraints (involving multiple columns) are skipped —
    those are handled by ``derive_from`` at Layer 4.

    Multi-CHECK merging: when a column has MULTIPLE single-column CHECK
    constraints (e.g., ``col >= 0`` as one CHECK and ``col <= 1000`` as
    another), the bounds are MERGED into a single range. Previously, the
    function returned on the first match, silently dropping the second
    bound — causing CHECK violations at fill time (e.g., generating
    ``low_stock_threshold = 5000`` when ``<= 1000`` was also required).
    Enum/format patterns (choice, boolean, pattern) are returned
    immediately on first match since they are mutually exclusive with
    range patterns.
    """
    # Normalize constraints (strip PG ::type casts and outer parens).
    constraints = _normalize_constraints(constraints)
    merged_gen: str | None = None
    merged_params: dict[str, Any] = {}
    for constraint in constraints:
        if not _is_single_column_check(col_name, constraint, all_columns):
            continue
        result = _parse_single_column_check(col_name, constraint.get("expression", ""))
        if result is None:
            continue
        gen, params = result
        # Enum/format patterns fully constrain the value space and retain
        # first-match priority over accumulated or subsequent bounds.
        if gen in {"choice", "boolean", "pattern"}:
            return result
        if merged_gen is None:
            merged_gen = gen
            merged_params = dict(params)
        else:
            merged_gen = _merge_single_column_bounds(merged_gen, merged_params, gen, params)
    if merged_gen is not None:
        return (merged_gen, merged_params)
    return None


def _parse_single_column_check(
    col_name: str,
    expr: str,
) -> tuple[str, dict[str, Any]] | None:
    """Parse a single-column CHECK expression and return (generator, params).

    Returns ``None`` if the expression doesn't match any known pattern.
    All patterns are case-insensitive and tolerate arbitrary whitespace.

    Handled patterns:
    - ``LENGTH(col) >= N`` / ``> N`` → string with ``min_length``
    - ``LENGTH(col) = N`` → string with ``min_length`` and ``max_length``
    - ``LENGTH(col) <= N`` / ``< N`` → string with ``max_length``
    - ``col LIKE '<literal>____' AND LENGTH(col) = N`` → pattern with regex
      ``^<literal>[A-Za-z0-9]{underscore_count}$`` (fixed-length code format)
    - ``LENGTH(col) = N AND col LIKE '<literal>____'`` → same as above (reversed)
    - ``col LIKE '<literal>____'`` → pattern with regex (standalone, no LENGTH)
    - ``col IN ('a', 'b', 'c')`` → choice generator (string enum)
    - ``col IN (0, 1)`` → boolean generator
    - ``col IN (1, 2, 3)`` → choice generator (numeric enum)
    - ``col BETWEEN X AND Y`` → integer/float with inclusive bounds
    - ``col >= X AND col <= Y`` → inclusive range
    - ``col > X AND col < Y`` → exclusive range
    - ``col > X AND col <= Y`` / ``col >= X AND col < Y`` → mixed range
    - ``col >= X`` / ``col > X`` → lower bound only
    - ``col <= Y`` / ``col < Y`` → upper bound only
    - ``col != 0`` → integer/float with ``min_value=1`` (or ``0.01`` for float)
    - ``col IS NULL OR <inner_expr>`` → strip prefix, parse inner expression
      (always generating a valid non-NULL value satisfies the CHECK)
    """
    # Normalize PG expression (strip ::type casts and outer parens).
    expr = _normalize_pg_check_expr(expr)
    col = re.escape(col_name)
    nullable_result = _parse_nullable_check(col_name, expr, col)
    if nullable_result is not None:
        return nullable_result

    # Keep the original pattern order: formats and enums precede ranges.
    for parse in (
        _parse_check_length,
        _parse_check_like,
        _parse_check_enum,
        _parse_check_inclusive_range,
        _parse_check_exclusive_range,
        _parse_check_lower_bound,
        _parse_check_upper_bound,
        _parse_check_nonzero,
    ):
        result = parse(col, expr)
        if result is not None:
            return result
    return None


def _parse_nullable_check(col_name: str, expr: str, col: str) -> tuple[str, dict[str, Any]] | None:
    """Parse an optional NULL branch before the remaining CHECK."""
    # Strip "col IS NULL OR ..." prefix (conditional NULL with inner constraint).
    # e.g., "phone IS NULL OR LENGTH(phone) = 11" → "LENGTH(phone) = 11"
    # e.g., "health_factor IS NULL OR (health_factor >= 1 AND health_factor <= 10)"
    #       → "health_factor >= 1 AND health_factor <= 10"
    # When the column CAN be NULL, always generating a valid non-NULL value
    # satisfies the CHECK (NULL is allowed but not required). This defers
    # to the inner expression's pattern matching.
    m_null_prefix = re.match(
        rf"^\s*{col}\s+IS\s+NULL\s+OR\s+(.+)$",
        expr,
        re.IGNORECASE,
    )
    if m_null_prefix:
        inner = m_null_prefix.group(1).strip()
        # Strip surrounding parentheses if present (e.g., "(col >= 1 AND col <= 10)")
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1].strip()
        result = _parse_single_column_check(col_name, inner)
        if result is not None:
            return result
    return None


def _parse_check_length(col: str, expr: str) -> tuple[str, dict[str, Any]] | None:
    """Parse minimum, exact and maximum string lengths."""
    # Pattern: LENGTH(col) >= N — minimum length constraint
    # e.g., LENGTH(name) >= 2
    # Uses pystr_min_length / pystr_max_length from Faker's pystr generator.
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*>=\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"min_length": n})

    # Pattern: LENGTH(col) > N — strictly greater than N
    # e.g., LENGTH(code) > 3 → min_length = 4
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*>\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"min_length": n + 1})

    # Pattern: LENGTH(col) = N — exact length
    # e.g., LENGTH(cvv) = 3 → both min and max length = 3
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*=\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"min_length": n, "max_length": n})

    # Pattern: LENGTH(col) <= N — maximum length constraint
    # e.g., LENGTH(description) <= 500
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*<=\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"max_length": n})

    # Pattern: LENGTH(col) < N — strictly less than N
    # e.g., LENGTH(label) < 20 → max_length = 19
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*<\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"max_length": n - 1})
    return None


def _parse_check_like(col: str, expr: str) -> tuple[str, dict[str, Any]] | None:
    """Parse fixed-length LIKE patterns in their original precedence order."""
    # Pattern: col LIKE '<literal>____' AND LENGTH(col) = N
    # e.g., color_code LIKE '#______' AND LENGTH(color_code) = 7
    # → pattern generator with regex ^<literal>[A-Za-z0-9]{underscore_count}$
    #
    # SQL LIKE wildcards: ``_`` matches any single char, ``%`` matches zero
    # or more chars. We only handle patterns where all wildcards are ``_``
    # (fixed-length), because ``%`` makes the length variable. Combined
    # with ``LENGTH(col) = N``, this constrains both the prefix and the
    # total length. The alphanumeric charset is the safest default for
    # code-style columns; users can override with a custom config for
    # specific charsets (e.g., hex for color codes).
    m = re.match(
        rf"^\s*{col}\s+LIKE\s+'([^']*)'\s+AND\s+LENGTH\s*\(\s*{col}\s*\)\s*=\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        like_pattern = m.group(1)
        total_len = int(m.group(2))
        if "%" not in like_pattern and like_pattern.count("_") > 0 and len(like_pattern) == total_len:
            regex = _like_to_regex(like_pattern)
            return ("pattern", {"regex": regex})

    # Pattern: LENGTH(col) = N AND col LIKE '<literal>____' (reversed order)
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*=\s*(\d+)\s+AND\s+{col}\s+LIKE\s+'([^']*)'\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        total_len = int(m.group(1))
        like_pattern = m.group(2)
        if "%" not in like_pattern and like_pattern.count("_") > 0 and len(like_pattern) == total_len:
            regex = _like_to_regex(like_pattern)
            return ("pattern", {"regex": regex})

    # Pattern: col LIKE '<literal>____' (standalone, no LENGTH)
    # Infer length from underscore count alone. Only handle when all
    # wildcards are ``_`` (fixed-length); ``%`` is skipped because the
    # variable length cannot be deterministically generated.
    m = re.match(
        rf"^\s*{col}\s+LIKE\s+'([^']*)'\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        like_pattern = m.group(1)
        if "%" not in like_pattern and like_pattern.count("_") > 0:
            regex = _like_to_regex(like_pattern)
            return ("pattern", {"regex": regex})
    return None


def _parse_check_enum(col: str, expr: str) -> tuple[str, dict[str, Any]] | None:
    """Parse string, PostgreSQL ANY, boolean and numeric enum constraints."""
    # Pattern: col IN ('a', 'b', 'c') — string enum
    m = re.match(
        rf"^\s*{col}\s+IN\s*\(\s*('[^']*'(?:\s*,\s*'[^']*')*)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        choices_str = m.group(1)
        choices = re.findall(r"'([^']*)'", choices_str)
        if choices:
            return ("choice", {"choices": choices})

    # Pattern: col = ANY (ARRAY['a'::text, 'b'::text, ...]) — PostgreSQL
    # normalizes ``col IN ('a', 'b')`` to this form in information_schema.
    # The ``::type`` casts are stripped from each value. Example:
    #   status = ANY (ARRAY['active'::text, 'inactive'::text, ...])
    # Without this pattern, all PostgreSQL IN-constrained columns would miss
    # CHECK inference, causing the L3 exact match ``choices: [0, 1]`` to leak
    # through for every ``status`` column.
    m = re.match(
        rf"^\s*{col}\s*=\s*ANY\s*\(\s*ARRAY\s*\[\s*(.+?)\s*\]\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        inner = m.group(1)
        # Extract quoted string values (strip ::type casts)
        choices = re.findall(r"'([^']*)'", inner)
        if choices:
            return ("choice", {"choices": choices})
        # Parse complete numeric literals, preserving signs and decimal values.
        numeric_choices = _parse_numeric_array_literals(inner)
        if numeric_choices:
            if (
                len(numeric_choices) == 2
                and all(isinstance(n, int) for n in numeric_choices)
                and set(numeric_choices) == {0, 1}
            ):
                return ("boolean", {})
            return ("choice", {"choices": numeric_choices})

    # Pattern: col IN (0, 1) or col IN (1, 0) — boolean
    m = re.match(
        rf"^\s*{col}\s+IN\s*\(\s*(0\s*,\s*1|1\s*,\s*0)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        return ("boolean", {})

    # Pattern: col IN (int, int, ...) — numeric enum (non-boolean)
    m = re.match(
        rf"^\s*{col}\s+IN\s*\(\s*([\d\s,]+)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        nums_str = m.group(1)
        nums = [int(n.strip()) for n in nums_str.split(",") if n.strip()]
        if len(nums) != 2 or set(nums) != {0, 1}:
            return ("choice", {"choices": nums})
    return None


def _parse_numeric_array_literals(inner: str) -> list[int | float] | None:
    """Read complete literals only when their decimal value survives serialization."""
    choices: list[int | float] = []
    for item in inner.split(","):
        literal = item.strip()
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", literal):
            return None
        value = int(literal) if re.fullmatch(r"[+-]?\d+", literal) else float(literal)
        if isinstance(value, float):
            try:
                if Decimal(str(value)) != Decimal(literal):
                    return None
            except InvalidOperation:
                return None
        choices.append(value)
    return choices


def _build_numeric_range(
    minimum: str, maximum: str, *, lower_exclusive: bool = False, upper_exclusive: bool = False
) -> tuple[str, dict[str, Any]]:
    """Build a numeric range with the existing integer or float boundary shifts."""
    is_integer = "." not in minimum and "." not in maximum
    min_value: int | float = int(minimum) if is_integer else float(minimum)
    max_value: int | float = int(maximum) if is_integer else float(maximum)
    step = 1 if is_integer else 0.01
    if lower_exclusive:
        min_value += step
    if upper_exclusive:
        max_value -= step
    return ("integer" if is_integer else "float", {"min_value": min_value, "max_value": max_value})


def _parse_check_inclusive_range(col: str, expr: str) -> tuple[str, dict[str, Any]] | None:
    """Parse BETWEEN and paired inclusive numeric bounds."""
    # Pattern: col BETWEEN X AND Y — inclusive range (SQL BETWEEN syntax)
    # Equivalent to col >= X AND col <= Y, but uses the BETWEEN keyword.
    # Common in DDL generated by ORM tools and manual schema definitions.
    m = re.match(
        rf"^\s*{col}\s+BETWEEN\s+(-?\d+(?:\.\d+)?)\s+AND\s+(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        return _build_numeric_range(m.group(1), m.group(2))

    # Pattern: col >= X AND col <= Y — inclusive range
    m = re.match(
        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        return _build_numeric_range(m.group(1), m.group(2))
    return None


def _parse_check_exclusive_range(col: str, expr: str) -> tuple[str, dict[str, Any]] | None:
    """Parse paired numeric bounds with one or two strict inequalities."""
    # Pattern: col > X AND col < Y — exclusive range (both bounds strict)
    # For integers: shift min up by 1, max down by 1.
    # For floats: add/subtract epsilon (0.01) to both bounds (see comment
    # in the ``col > X AND col <= Y`` pattern above for rationale).
    m = re.match(
        rf"^\s*{col}\s*>\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        return _build_numeric_range(m.group(1), m.group(2), lower_exclusive=True, upper_exclusive=True)

    # Pattern: col > X AND col <= Y — mixed range (exclusive lower, inclusive upper)
    # e.g., interest_rate > 0 AND interest_rate <= 0.3
    # e.g., rate > 0.0 AND rate <= 0.25
    # For integers: shift min up by 1 (X+1) to satisfy strict inequality.
    # For floats: add epsilon (0.01) to min_value. ``random.uniform(X, Y)``
    # CAN return X (both endpoints are inclusive in Python), which would
    # violate the strict ``> X`` CHECK. ConstraintSolver does NOT retry
    # CHECK violations (only UNIQUE), so a single 0.0 value aborts the
    # entire fill. Adding 0.01 ensures all generated values are strictly
    # greater than X.
    m = re.match(
        rf"^\s*{col}\s*>\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        return _build_numeric_range(m.group(1), m.group(2), lower_exclusive=True)

    # Pattern: col >= X AND col < Y — mixed range (inclusive lower, exclusive upper)
    # e.g., score >= 0 AND score < 100
    # For integers: shift max down by 1 (Y-1) to satisfy strict inequality.
    # For floats: subtract epsilon (0.01) from max_value for the same reason
    # as above — ``random.uniform`` can return Y, violating ``< Y``.
    m = re.match(
        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        return _build_numeric_range(m.group(1), m.group(2), upper_exclusive=True)
    return None


def _parse_check_lower_bound(col: str, expr: str) -> tuple[str, dict[str, Any]] | None:
    """Parse an inclusive or exclusive numeric lower bound."""
    # Pattern: col >= X — lower bound only (inclusive)
    m = re.match(
        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(val_str)})
        return (gen, {"min_value": float(val_str)})

    # Pattern: col > X — lower bound only (exclusive)
    m = re.match(
        rf"^\s*{col}\s*>\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(val_str) + 1})
        # For floats, the CHECK is strict (>), but ``min_value`` is inclusive
        # (>=). If we set ``min_value = X``, the generator can produce X
        # (e.g., ``random.uniform(0.0, max)`` can return 0.0), which fails
        # the strict ``> X`` CHECK. Add a small epsilon to ensure all
        # generated values are strictly greater than X.
        return (gen, {"min_value": float(val_str) + 0.01})
    return None


def _parse_check_upper_bound(col: str, expr: str) -> tuple[str, dict[str, Any]] | None:
    """Parse an inclusive or exclusive numeric upper bound."""
    # Pattern: col <= Y — upper bound only (inclusive)
    m = re.match(
        rf"^\s*{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"max_value": int(val_str)})
        return (gen, {"max_value": float(val_str)})

    # Pattern: col < Y — upper bound only (exclusive)
    m = re.match(
        rf"^\s*{col}\s*<\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"max_value": int(val_str) - 1})
        # For floats, ``max_value`` is inclusive (<=) but the CHECK is strict
        # (<). Subtract a small epsilon so the generator never produces Y.
        return (gen, {"max_value": float(val_str) - 0.01})
    return None


def _parse_check_nonzero(col: str, expr: str) -> tuple[str, dict[str, Any]] | None:
    """Parse the supported nonzero numeric exclusion constraint."""
    # Pattern: col != N — inequality with a literal (excludes a single value)
    # e.g., quantity != 0, status != -1
    # For ``col != 0`` (the most common case): generate positive non-zero
    # values by setting min_value=1 (integer) or min_value=0.01 (float).
    # This is a pragmatic choice — most real-world columns with ``!= 0``
    # (quantity, count, amount) expect positive values. For ``col != N``
    # where N != 0: skip (cannot reliably exclude a single value from a
    # random range without the choice generator, and guessing a safe range
    # would be arbitrary).
    m = re.match(
        rf"^\s*{col}\s*!=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        if is_int and int(val_str) == 0:
            return ("integer", {"min_value": 1})
        if not is_int and float(val_str) == 0.0:
            return ("float", {"min_value": 0.01})
    return None
