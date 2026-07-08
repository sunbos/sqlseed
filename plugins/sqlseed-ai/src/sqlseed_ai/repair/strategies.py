"""Layer 3: Stateless repair strategies.

Each function follows signature ``(col: dict, v: ViolationReport, ctx: dict) -> dict``.
Stateless: no shared mutable state, no ordering dependencies.

Spec reference: Section 5.3.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlseed_ai.validator.models import ViolationReport

RepairFn = Callable[[dict[str, Any], ViolationReport, dict[str, Any]], dict[str, Any]]


# Whitelist of safe params for each generator (Rule #14 Layer 3).
# Aligned with actual generator signatures in
# ``src/sqlseed/generators/base_provider.py`` (and faker/mimesis overrides).
# Phase 4 Task 4.1: expanded from 13 → 36 entries to match the legacy
# ``_GENERATOR_ACCEPTED_PARAMS`` (deleted with ``staged_analyzer.py``) and
# fixed param-name bugs (``date``/``datetime`` used ``min_year``/``max_year``
# but the generators accept ``start_year``/``end_year``).
_GENERATOR_PARAM_WHITELIST: dict[str, set[str]] = {
    "integer": {"min_value", "max_value"},
    "random_int": {"min_value", "max_value"},
    "random_float": {"min_value", "max_value", "precision"},
    "string": {"min_length", "max_length", "charset"},
    "text": {"min_length", "max_length"},
    "bytes": {"length"},
    "boolean": set(),
    "name": set(),
    "first_name": set(),
    "last_name": set(),
    "email": set(),
    "phone": set(),
    "address": set(),
    "company": set(),
    "url": set(),
    "ipv4": set(),
    "uuid": set(),
    "date": {"start_year", "end_year"},
    "datetime": {"start_year", "end_year"},
    "timestamp": set(),
    "sentence": set(),
    "password": {"length"},
    "choice": {"choices"},
    "weighted_choice": {"choices", "weighted_choices"},
    "json": {"schema"},
    "pattern": {"pattern", "regex"},
    "username": set(),
    "city": set(),
    "country": set(),
    "state": set(),
    "zip_code": set(),
    "job_title": set(),
    "country_code": set(),
    "word": set(),
    "catch_phrase": set(),
    "template": {"template", "sequence_start", "sequence_step"},
}


def _strip_invalid_params(params: dict[str, Any], generator: str) -> dict[str, Any]:
    """Remove params not in the generator's whitelist."""
    whitelist = _GENERATOR_PARAM_WHITELIST.get(generator)
    if whitelist is None:
        return params
    return {k: v for k, v in params.items() if k in whitelist}


def _infer_template_prefix(col_name: str) -> str:
    """Infer a template prefix from column name (e.g., order_code → ORDER)."""
    if not col_name:
        return "ID"
    parts = col_name.split("_")
    if len(parts) > 1:
        return parts[0].upper()
    return col_name[:4].upper()


def _semantic_upgrade(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a generic string generator based on column-name heuristics.

    Mirrors Rule #28 (exact_match_upgrade) for the post-repair path: if the
    column name matches a known semantic pattern (email, phone, url, uuid,
    description, name, company), swap to the more specific generator.
    Otherwise keep the existing generator (e.g., "string").

    Adversarial fix (C5): the plan had two conflicting definitions of
    ``_semantic_upgrade`` — the second one (which won) defaulted to "word",
    breaking ``test_switch_generator_to_string_keeps_string_when_no_pattern_matches``.
    This unified version keeps the existing generator when no pattern matches.

    Blind-spot fix (2026-07-09): when upgrading ``string`` → ``phone`` for a
    phone-like column that has a ``LENGTH(col) = N`` CHECK constraint, upgrade
    to ``pattern`` with ``[0-9]{N}`` instead of ``phone``. The ``phone``
    generator produces variable-length output (NANP format is 14 chars), which
    violates ``LENGTH(phone) = 11`` style constraints. Previously,
    ``_semantic_upgrade`` unconditionally dropped all params (including
    ``min_length``/``max_length`` from CHECK inference), causing the LENGTH
    CHECK to be violated and triggering LLM oscillation between ``string``
    (satisfies LENGTH but semantically wrong) and ``phone`` (semantically
    correct but violates LENGTH).
    """
    name = col.get("name", "")
    name_lower = name.lower()
    new_gen: str | None = None
    if "email" in name_lower:
        new_gen = "email"
    elif name_lower in ("phone", "mobile", "telephone", "tel"):
        new_gen = "phone"
    elif "url" in name_lower or "website" in name_lower:
        new_gen = "url"
    elif "uuid" in name_lower or "guid" in name_lower:
        new_gen = "uuid"
    elif name_lower in ("description", "desc", "comment", "note"):
        new_gen = "sentence"
    elif name_lower.endswith("_name") or name_lower == "name":
        new_gen = "name"
    elif name_lower in ("merchant", "company") or "company" in name_lower:
        new_gen = "company"
    new_col = {**col}
    if new_gen is not None:
        # Blind-spot fix: phone-like column with LENGTH CHECK → pattern with
        # [0-9]{N} instead of phone generator. This satisfies both the semantic
        # requirement (digits-only, phone-like) and the LENGTH CHECK (exact N).
        if new_gen == "phone":
            length_n = _extract_length_check(name, ctx)
            if length_n is not None:
                new_col["generator"] = "pattern"
                new_col["params"] = {"regex": f"[0-9]{{{length_n}}}"}
                new_col.pop("derive_from", None)
                new_col.pop("expression", None)
                return new_col
        new_col["generator"] = new_gen
    # else: keep existing generator (e.g., "string")
    new_col.pop("params", None)
    return new_col


def _extract_length_check(col_name: str, ctx: dict[str, Any]) -> int | None:
    """Extract N from a ``LENGTH(col) = N`` CHECK constraint.

    Returns the integer N if the column has an exact-length CHECK constraint,
    or ``None`` if no such constraint exists.
    """
    table_schema = ctx.get("table_schema")
    if not table_schema or not col_name:
        return None
    for c in table_schema.constraints:
        if c.get("type") != "check":
            continue
        expr = c.get("expression", "")
        if not isinstance(expr, str):
            continue
        # Strip "col IS NULL OR " prefix to handle nullable LENGTH constraints
        # e.g., "phone IS NULL OR LENGTH(phone) = 11" → "LENGTH(phone) = 11"
        prefix = rf"{re.escape(col_name)}\s+IS\s+NULL\s+OR\s+"
        expr = re.sub(prefix, "", expr, flags=re.IGNORECASE)
        m = re.match(
            rf"^\s*LENGTH\s*\(\s*{re.escape(col_name)}\s*\)\s*=\s*(\d+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            return int(m.group(1))
    return None


def _switch_generator(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Switch to a different generator, with semantic upgrade when target is string.

    Adversarial fix (C5 from cross-agent review): Spec version called
    ``_semantic_upgrade`` when switching to "string" target (to upgrade
    generic string → email/url/etc. based on column name). The original
    Plan version omitted this call, causing a behavior drift. We align
    with the Spec version (smarter behavior) and delegate to the shared
    ``_semantic_upgrade`` helper below.
    """
    target = v.fix_params.get("target", "string")
    new_col = {**col, "generator": target}
    if target == "string":
        new_col = _semantic_upgrade(new_col, v, ctx)
    new_col.pop("params", None)
    return new_col


def _upgrade_to_template(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Replace generator with template (UNIQUE code-like columns).

    Skips numeric columns (INT/REAL/FLOAT/etc.) — the ``template`` generator
    produces strings like ``DAY-0001``, which SQLite cannot coerce to INTEGER
    when the column is part of a composite PK or has a NOT NULL constraint.
    For numeric UNIQUE columns, the ConstraintSolver's backtracking handles
    uniqueness without needing a template generator.
    """
    # Skip numeric column types — template generates strings, which fail on
    # INTEGER/REAL columns (SQLite raises NOT NULL when string→int conversion
    # fails or produces NULL).
    col_type = (ctx.get("column_type") or "").upper()
    if col_type and any(k in col_type for k in ("INT", "REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")):
        return col

    # Skip columns with CHECK constraints — the template generator would
    # override CHECK-based inference (e.g., day_of_week BETWEEN 0 AND 6 should
    # produce integers, not "DAY-0001" strings).
    table_schema = ctx.get("table_schema")
    if table_schema:
        col_name = col.get("name", "")
        for c in table_schema.constraints:
            if c.get("type") != "check":
                continue
            expr = c.get("expression", "")
            if col_name and re.search(rf"\b{re.escape(col_name)}\b", expr, re.IGNORECASE):
                return col

    col_name = col.get("name", "row")
    prefix = _infer_template_prefix(col_name)
    return {
        **col,
        "generator": "template",
        "params": {"template": f"{prefix}-{{sequence:04d}}"},
        "derive_from": None,
        "expression": None,
    }


def _normalize_params(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Normalize choice/weighted_choice params and strip invalid params (Rule #14).

    Phase 4 Task 4.1: expanded to strip params for ALL generators (not just
    choice-family) using ``_GENERATOR_PARAM_WHITELIST``. This makes the
    strategy the canonical implementation of legacy Rule #14, suitable for
    delegation from ``AiConfigRefiner._apply_rule_14_param_stripping``.
    """
    params = col.get("params")
    gen = col.get("generator", "")
    new_col = {**col}
    if gen in {"choice", "weighted_choice"} and isinstance(params, list):
        new_col["params"] = {"choices": params}
        params = new_col["params"]
    if gen == "weighted_choice" and isinstance(params, dict):
        choices = params.get("choices", [])
        if choices and any(isinstance(c, str) for c in choices):
            new_col["generator"] = "choice"
            gen = "choice"
    if isinstance(params, dict) and "choice" in params and "choices" not in params:
        new_col["params"] = {"choices": params["choice"]}
        params = new_col["params"]
    if isinstance(params, dict):
        new_col["params"] = _strip_invalid_params(params, gen)
    return new_col


def _break_derive_from_cycle(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Strip derive_from + expression and assign fallback generator."""
    new_col = {**col}
    new_col["derive_from"] = None
    new_col["expression"] = None
    if "generator" not in new_col:
        col_type = ctx.get("column_type", "TEXT")
        new_col["generator"] = "integer" if "INT" in col_type.upper() else "string"
    return new_col


def _adjust_bounds(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Adjust min_value/max_value bounds from fix_params."""
    new_col = {**col}
    params = dict(new_col.get("params") or {})
    for k in ("min_value", "max_value"):
        if k in v.fix_params:
            params[k] = v.fix_params[k]
    new_col["params"] = params
    return new_col


def _align_fk_max_value(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Align FK column max_value to parent PK range."""
    new_col = {**col}
    params = dict(new_col.get("params") or {})
    if "max_value" in v.fix_params:
        params["max_value"] = v.fix_params["max_value"]
    new_col["params"] = params
    return new_col


def _isolate_date_ranges(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Isolate date ranges (min_year/max_year) from fix_params."""
    new_col = {**col}
    params = dict(new_col.get("params") or {})
    for k in ("min_year", "max_year"):
        if k in v.fix_params:
            params[k] = v.fix_params[k]
    new_col["params"] = params
    return new_col


def _fix_self_reference(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Strip derive_from + expression when column self-references."""
    new_col = {**col}
    new_col["derive_from"] = None
    new_col["expression"] = None
    if "generator" not in new_col:
        col_type = ctx.get("column_type", "TEXT")
        new_col["generator"] = "integer" if "INT" in col_type.upper() else "string"
    return new_col


def _coerce_float_to_int(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Rewrite random_float → random_int for INTEGER columns (Rule #26)."""
    new_col = {**col}
    if new_col.get("generator") == "random_float":
        new_col["generator"] = "random_int"
    return new_col


def _align_group_generators(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Align composite FK group to a single generator (integer by default)."""
    new_col = {**col, "generator": "integer"}
    new_col.pop("params", None)
    return new_col


def _expand_pool(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Expand choice pool to satisfy UNIQUE cardinality."""
    new_col = {**col}
    params = dict(new_col.get("params") or {})
    choices = list(params.get("choices") or [])
    row_count = ctx.get("row_count", 1000)
    if len(choices) < row_count * 2:
        # Generate more choices by appending suffixes
        base = choices[:10] if choices else ["item"]
        while len(choices) < row_count * 2:
            choices = choices + [f"{c}_{len(choices)}" for c in base]
        params["choices"] = choices
    new_col["params"] = params
    return new_col


def _add_unique_suffix(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Alias for upgrade_to_template (UNIQUE with suffix)."""
    return _upgrade_to_template(col, v, ctx)


# === Task 2.1: Rule #15 — bound_regex ===
_UNBOUNDED_REGEX_PATTERN = re.compile(r"\{(\d+),\}")


def _bound_unbounded_quantifier(match: re.Match[str]) -> str:
    """Replace {N,} with {N,N+5} to bound unbounded quantifiers."""
    n = int(match.group(1))
    return f"{{{n},{n + 5}}}"


def _bound_regex(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Bound unbounded regex quantifiers {N,} → {N,N+5} (Rule #15).

    Unbounded quantifiers like ``{3,}`` can cause catastrophic backtracking
    in regex evaluation. Bounding them to ``{3,8}`` keeps the regex fast
    while still allowing sufficient variability.
    """
    if col.get("generator") not in ("pattern",):
        return col
    new_col = {**col}
    params = dict(new_col.get("params") or {})
    for key in ("regex", "pattern"):
        val = params.get(key)
        if isinstance(val, str):
            params[key] = _UNBOUNDED_REGEX_PATTERN.sub(_bound_unbounded_quantifier, val)
    new_col["params"] = params
    return new_col


# === Task 2.2: Rule #18 — cap_future_end_year ===
def _cap_future_end_year(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Cap unreasonable future end_year on date/datetime generators (Rule #18).

    LLMs sometimes return ``end_year: 2100`` producing test data in the
    2090s. Cap at ``current_year + 1`` for a small lookahead without
    producing 22nd-century data. Only applies to ``date`` and ``datetime``
    generators (``timestamp`` accepts no params).
    """
    if col.get("generator") not in ("date", "datetime"):
        return col
    params = col.get("params")
    if not isinstance(params, dict):
        return col
    end_year = params.get("end_year")
    if not isinstance(end_year, int):
        return col
    cap = datetime.now().year + 1
    if end_year > cap:
        new_col = {**col}
        new_params = dict(params)
        new_params["end_year"] = cap
        new_col["params"] = new_params
        return new_col
    return col


# === Task 2.3: Rule #25 — downgrade_text_to_string ===
def _is_code_like_column(name: str) -> bool:
    """Heuristic: column name looks like a code/identifier (Rule #25 helper)."""
    if not name:
        return False
    lower = name.lower()
    suffixes = ("_code", "code", "_id", "sku", "_no", "number", "_key")
    return any(lower.endswith(s) for s in suffixes) or lower in ("code", "sku", "isbn")


def _downgrade_text_to_string(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Downgrade text → string for UNIQUE code-like columns (Rule #25).

    ``text`` produces paragraph-length values that may exceed the column's
    intended length on UNIQUE code columns. Switch to ``string`` with a
    bounded ``max_length`` (default 20) so the value fits a code-like field.
    """
    if col.get("generator") not in ("text", "word"):
        return col
    name = col.get("name", "")
    if not _is_code_like_column(name):
        return col
    new_col = {**col, "generator": "string"}
    params = dict(new_col.get("params") or {})
    if "max_length" not in params or params["max_length"] > 50:
        params["max_length"] = 20
    new_col["params"] = params
    return new_col


# === Task 2.4: Rule #23 — upgrade_phone_to_pattern ===
_NANP_PHONE_REGEX = r"^\+1-[2-9]\d{2}-[2-9]\d{2}-\d{4}$"

_PHONE_NAME_KEYWORDS = frozenset(
    {
        "phone",
        "mobile",
        "telephone",
        "tel",
        "cell",
        "cellphone",
        "contact_number",
    }
)


def _is_phone_like(name: str) -> bool:
    """Heuristic: column name looks like a phone number field."""
    if not name:
        return False
    lower = name.lower()
    if lower in _PHONE_NAME_KEYWORDS:
        return True
    return any(lower.endswith(suffix) for suffix in ("_phone", "_mobile", "_tel", "_telephone"))


def _upgrade_phone_to_pattern(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Upgrade phone-like columns to a strict NANP pattern (Rule #23).

    The Faker ``phone`` generator emits mixed formats across rows. Real
    front-end validation expects a single consistent format. Upgrading to
    ``pattern`` with the NANP regex guarantees uniform output.

    Triggers on phone-like column names with ``phone`` (no params),
    ``string``, or ``pattern`` with all-digits regex.

    Skips columns with a ``LENGTH(col) = N`` CHECK constraint — the NANP
    regex produces 14-character strings (``+1-XXX-XXX-XXXX``), which would
    violate constraints like ``LENGTH(phone) = 11``. In that case, the
    CHECK-based inference (``string`` with ``min_length``/``max_length``)
    already handles the column correctly.
    """
    name = col.get("name", "")
    if not _is_phone_like(name):
        return col

    # Skip if column has a LENGTH(col) CHECK constraint — NANP regex is 14
    # chars and would violate LENGTH(phone) = 11 style constraints.
    table_schema = ctx.get("table_schema")
    if table_schema:
        for c in table_schema.constraints:
            if c.get("type") != "check":
                continue
            expr = c.get("expression", "")
            if re.search(rf"LENGTH\s*\(\s*{re.escape(name)}\s*\)", expr, re.IGNORECASE):
                return col

    gen = col.get("generator")
    if gen == "phone":
        params = col.get("params") or {}
        if params:
            return col  # Don't touch phone with explicit params
        return {**col, "generator": "pattern", "params": {"regex": _NANP_PHONE_REGEX}}
    if gen == "string":
        return {**col, "generator": "pattern", "params": {"regex": _NANP_PHONE_REGEX}}
    if gen == "pattern":
        params = col.get("params") or {}
        regex = params.get("regex", "")
        # If regex is all-digits (no [2-9] enforcement), upgrade to NANP
        if isinstance(regex, str) and "[2-9]" not in regex and regex:
            new_params = dict(params)
            new_params["regex"] = _NANP_PHONE_REGEX
            return {**col, "params": new_params}
    return col


# === Task 2.5: Rule #32 — coerce_to_boolean_enum ===
def _coerce_to_boolean_enum(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Coerce column to boolean/choice when CHECK constraint is {0,1} or {true,false} (Rule #32).

    ``fix_params.check_values`` is the list of allowed values from the
    CHECK constraint. If all values are 0/1 (int), switch to ``boolean``.
    If all values are 'true'/'false' (str), switch to ``choice`` with
    those values.
    """
    check_values = v.fix_params.get("check_values") or []
    if not check_values:
        return col
    # Boolean int: {0, 1}
    if all(val in (0, 1) for val in check_values):
        return {**col, "generator": "boolean", "params": {}}
    # Boolean string: {'true', 'false'} (any case)
    lower_values = [str(val).lower() for val in check_values]
    if set(lower_values) <= {"true", "false"}:
        return {**col, "generator": "choice", "params": {"choices": lower_values}}
    return col


# === Task 2.6: Rule #17 — handle_boolean_derive ===
def _handle_boolean_derive(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Strip derive_from on boolean-enum columns and assign boolean generator (Rule #17).

    Boolean columns (CHECK(x IN (0,1)) or CHECK(x IN ('true','false')))
    cannot be derived from other columns via simple expressions — the
    expression would need to return exactly 0/1 or 'true'/'false', which
    is fragile. Strip derive_from and assign ``boolean`` generator; the
    CHECK constraint is satisfied natively.
    """
    new_col = {**col}
    new_col.pop("derive_from", None)
    new_col.pop("expression", None)
    new_col["generator"] = "boolean"
    new_col.pop("params", None)
    return new_col


# === Task 2.7: Rule #33 — coerce_to_text_enum ===
def _coerce_to_text_enum(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Coerce text column to choice generator when CHECK constraint lists string values (Rule #33).

    If the CHECK constraint restricts the column to a small set of string
    values (e.g., ``CHECK(status IN ('draft','published','archived'))``),
    switch to ``choice`` generator with those values as ``choices``.

    No-op when check_values are integers (handled by Rule #32 boolean_enum).
    """
    check_values = v.fix_params.get("check_values") or []
    if not check_values:
        return col
    # Only handle string values (Rule #32 handles 0/1 integers)
    if not all(isinstance(val, str) for val in check_values):
        return col
    return {**col, "generator": "choice", "params": {"choices": list(check_values)}}


# === Task 2.8: Rule #27 — infer_derive_from_check ===
def _infer_derive_from_check(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Infer derive_from from CHECK constraint (Rule #27).

    When a CHECK constraint implies a column relationship (e.g.,
    ``CHECK(end_date >= start_date)``), set ``derive_from`` to the source
    column and assign a timedelta-based expression so the constraint is
    satisfied by construction.

    ``fix_params`` carries:
      - ``source_col``: name of the column to derive from
      - ``expression``: the expression to apply (must use ``timedelta``
        for date columns; Rule #36 strips non-timedelta expressions)
    """
    source_col = v.fix_params.get("source_col")
    expression = v.fix_params.get("expression")
    if not source_col or not expression:
        return col
    new_col = {**col}
    new_col["derive_from"] = source_col
    new_col["expression"] = expression
    # Per ColumnConfig mutual exclusivity, generator/params must be stripped
    new_col.pop("generator", None)
    new_col.pop("params", None)
    return new_col


# === Task 2.9: Rule #31 — strip_composite_unique ===
def _strip_composite_unique(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Strip constraints.unique:true from composite-only UNIQUE columns (Rule #31).

    Composite UNIQUE constraints (e.g., ``UNIQUE(tenant_id, email)``) do
    not make individual columns unique. Removing ``unique: true`` prevents
    UNIQUE exhaustion at fill time.
    """
    new_col = {**col}
    constraints = dict(new_col.get("constraints") or {})
    constraints.pop("unique", None)
    if constraints:
        new_col["constraints"] = constraints
    else:
        new_col.pop("constraints", None)
    return new_col


# === Task 2.10: Rule #34 — align_check_bounds ===
def _align_check_bounds(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Align generator min_value/max_value to CHECK constraint bounds (Rule #34).

    When a CHECK constraint imposes a bound (e.g., ``CHECK(price <= 1000)``
    or ``CHECK(balance >= 0)``), the generator's ``min_value``/``max_value``
    must be within the CHECK range. ``fix_params`` carries the target
    bounds extracted from the CHECK expression.
    """
    new_col = {**col}
    params = dict(new_col.get("params") or {})
    if "min_value" in v.fix_params:
        current_min = params.get("min_value")
        target_min = v.fix_params["min_value"]
        if current_min is None or current_min < target_min:
            params["min_value"] = target_min
    if "max_value" in v.fix_params:
        current_max = params.get("max_value")
        target_max = v.fix_params["max_value"]
        if current_max is None or current_max > target_max:
            params["max_value"] = target_max
    new_col["params"] = params
    return new_col


# === Task 2.11: Rule #35 — strip_generator_from_derive_from ===
def _strip_generator_from_derive_from(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Strip generator/params from columns with derive_from (Rule #35).

    ``ColumnConfig`` enforces mutual exclusivity: a column is either in
    source mode (``generator`` + ``params``) or derived mode
    (``derive_from`` + ``expression``). When the LLM emits both, strip
    the generator/params to satisfy Pydantic validation.
    """
    if not col.get("derive_from"):
        return col
    new_col = {**col}
    new_col.pop("generator", None)
    new_col.pop("params", None)
    return new_col


# === Task 2.12: Rule #36 — strip_invalid_date_derive_from ===
_DATE_GENERATORS = frozenset({"date", "datetime"})
_DATE_NAME_PATTERNS = ("_at", "_date", "_time", "_on", "date_", "time_", "timestamp")


def _looks_like_date_column(name: str | None, generators: dict[str, str | None]) -> bool:
    """Heuristic: column is a date column by name or generator."""
    if not isinstance(name, str):
        return False
    if generators.get(name) in _DATE_GENERATORS:
        return True
    lower = name.lower()
    return any(lower.endswith(p) or lower.startswith(p) for p in _DATE_NAME_PATTERNS)


def _strip_invalid_date_derive_from(col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]) -> dict[str, Any]:
    """Strip derive_from on date columns with non-timedelta expression (Rule #36).

    LLMs sometimes generate expressions like ``value + random_float(0, value)``
    for date columns, which crashes at runtime because you can't add a float
    to a date. This strategy strips the derive_from so Layer 4 (LLM Healer)
    or Rule #22 (range isolation) can handle the date column differently.

    A column is considered a "date column" if:
      1. Its own ``generator`` is ``date``/``datetime``, OR
      2. Any source column in ``derive_from`` has a date generator, OR
      3. The column name OR any source name matches a date-like pattern.
    """
    if not col.get("derive_from"):
        return col
    expr = col.get("expression")
    if not isinstance(expr, str) or "timedelta" in expr:
        return col

    # Build generator map from ctx (table_config) for source column lookup
    table_config = ctx.get("table_config") or {}
    generators: dict[str, str | None] = {}
    for c in table_config.get("columns", []):
        if isinstance(c, dict):
            n = c.get("name", "")
            g = c.get("generator")
            generators[n] = g if isinstance(g, str) else None

    col_name = col.get("name", "")
    sources = col["derive_from"]
    if isinstance(sources, str):
        sources = [sources]

    is_date = _looks_like_date_column(col_name, generators)
    if not is_date:
        for s in sources:
            if isinstance(s, str) and _looks_like_date_column(s, generators):
                is_date = True
                break

    if not is_date:
        return col

    new_col = {**col}
    new_col.pop("derive_from", None)
    new_col.pop("expression", None)
    # Ensure a date generator is set (fallback if generator was previously None)
    if not new_col.get("generator"):
        new_col["generator"] = "datetime"
    return new_col


REPAIR_STRATEGIES: dict[str, RepairFn] = {
    "switch_generator": _switch_generator,
    "upgrade_to_template": _upgrade_to_template,
    "normalize_params": _normalize_params,
    "break_derive_from_cycle": _break_derive_from_cycle,
    "adjust_bounds": _adjust_bounds,
    "align_fk_max_value": _align_fk_max_value,
    "isolate_date_ranges": _isolate_date_ranges,
    "semantic_upgrade": _semantic_upgrade,
    "fix_self_reference": _fix_self_reference,
    "coerce_float_to_int": _coerce_float_to_int,
    "align_group_generators": _align_group_generators,
    "expand_pool": _expand_pool,
    "add_unique_suffix": _add_unique_suffix,
    "bound_regex": _bound_regex,
    "cap_future_end_year": _cap_future_end_year,
    "downgrade_text_to_string": _downgrade_text_to_string,
    "upgrade_phone_to_pattern": _upgrade_phone_to_pattern,
    "coerce_to_boolean_enum": _coerce_to_boolean_enum,
    "handle_boolean_derive": _handle_boolean_derive,
    "coerce_to_text_enum": _coerce_to_text_enum,
    "infer_derive_from_check": _infer_derive_from_check,
    "strip_composite_unique": _strip_composite_unique,
    "align_check_bounds": _align_check_bounds,
    "strip_generator_from_derive_from": _strip_generator_from_derive_from,
    "strip_invalid_date_derive_from": _strip_invalid_date_derive_from,
}
