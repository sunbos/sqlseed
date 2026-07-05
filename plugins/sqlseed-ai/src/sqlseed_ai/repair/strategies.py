"""Layer 3: Stateless repair strategies.

Each function follows signature ``(col: dict, v: ViolationReport, ctx: dict) -> dict``.
Stateless: no shared mutable state, no ordering dependencies.

Spec reference: Section 5.3.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlseed_ai.validator.models import ViolationReport

RepairFn = Callable[[dict[str, Any], ViolationReport, dict[str, Any]], dict[str, Any]]


# Whitelist of safe params for each generator (Rule #14 Layer 3)
_GENERATOR_PARAM_WHITELIST: dict[str, set[str]] = {
    "integer": {"min_value", "max_value"},
    "random_int": {"min_value", "max_value"},
    "random_float": {"min_value", "max_value"},
    "string": {"min_length", "max_length"},
    "text": {"max_length"},
    "choice": {"choices"},
    "weighted_choice": {"choices", "weights"},
    "template": {"template"},
    "datetime": {"min_year", "max_year"},
    "date": {"min_year", "max_year"},
    "email": set(),
    "phone": set(),
    "pattern": {"regex"},
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


def _semantic_upgrade(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Upgrade a generic string generator based on column-name heuristics.

    Mirrors Rule #28 (exact_match_upgrade) for the post-repair path: if the
    column name matches a known semantic pattern (email, phone, url, uuid,
    description, name, company), swap to the more specific generator.
    Otherwise keep the existing generator (e.g., "string").

    Adversarial fix (C5): the plan had two conflicting definitions of
    ``_semantic_upgrade`` — the second one (which won) defaulted to "word",
    breaking ``test_switch_generator_to_string_keeps_string_when_no_pattern_matches``.
    This unified version keeps the existing generator when no pattern matches.
    """
    name = (col.get("name") or "").lower()
    new_gen: str | None = None
    if "email" in name:
        new_gen = "email"
    elif name in ("phone", "mobile", "telephone", "tel"):
        new_gen = "phone"
    elif "url" in name or "website" in name:
        new_gen = "url"
    elif "uuid" in name or "guid" in name:
        new_gen = "uuid"
    elif name in ("description", "desc", "comment", "note"):
        new_gen = "sentence"
    elif name.endswith("_name") or name == "name":
        new_gen = "name"
    elif name in ("merchant", "company") or "company" in name:
        new_gen = "company"
    new_col = {**col}
    if new_gen is not None:
        new_col["generator"] = new_gen
    # else: keep existing generator (e.g., "string")
    new_col.pop("params", None)
    return new_col


def _switch_generator(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
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


def _upgrade_to_template(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Replace generator with template (UNIQUE code-like columns)."""
    col_name = col.get("name", "row")
    prefix = _infer_template_prefix(col_name)
    return {
        **col,
        "generator": "template",
        "params": {"template": f"{prefix}-{{sequence:04d}}"},
        "derive_from": None,
        "expression": None,
    }


def _normalize_params(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Normalize choice/weighted_choice params (Rule #14 Layer 3)."""
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
    if gen in {"choice", "weighted_choice"} and isinstance(params, dict):
        new_col["params"] = _strip_invalid_params(params, gen)
    return new_col


def _break_derive_from_cycle(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Strip derive_from + expression and assign fallback generator."""
    new_col = {**col}
    new_col["derive_from"] = None
    new_col["expression"] = None
    if "generator" not in new_col:
        col_type = ctx.get("column_type", "TEXT")
        new_col["generator"] = "integer" if "INT" in col_type.upper() else "string"
    return new_col


def _adjust_bounds(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Adjust min_value/max_value bounds from fix_params."""
    new_col = {**col}
    params = dict(new_col.get("params") or {})
    for k in ("min_value", "max_value"):
        if k in v.fix_params:
            params[k] = v.fix_params[k]
    new_col["params"] = params
    return new_col


def _align_fk_max_value(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Align FK column max_value to parent PK range."""
    new_col = {**col}
    params = dict(new_col.get("params") or {})
    if "max_value" in v.fix_params:
        params["max_value"] = v.fix_params["max_value"]
    new_col["params"] = params
    return new_col


def _isolate_date_ranges(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Isolate date ranges (min_year/max_year) from fix_params."""
    new_col = {**col}
    params = dict(new_col.get("params") or {})
    for k in ("min_year", "max_year"):
        if k in v.fix_params:
            params[k] = v.fix_params[k]
    new_col["params"] = params
    return new_col


def _fix_self_reference(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Strip derive_from + expression when column self-references."""
    new_col = {**col}
    new_col["derive_from"] = None
    new_col["expression"] = None
    if "generator" not in new_col:
        col_type = ctx.get("column_type", "TEXT")
        new_col["generator"] = "integer" if "INT" in col_type.upper() else "string"
    return new_col


def _coerce_float_to_int(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Rewrite random_float → random_int for INTEGER columns (Rule #26)."""
    new_col = {**col}
    if new_col.get("generator") == "random_float":
        new_col["generator"] = "random_int"
    return new_col


def _align_group_generators(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Align composite FK group to a single generator (integer by default)."""
    new_col = {**col, "generator": "integer"}
    new_col.pop("params", None)
    return new_col


def _expand_pool(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
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


def _add_unique_suffix(
    col: dict[str, Any], v: ViolationReport, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Alias for upgrade_to_template (UNIQUE with suffix)."""
    return _upgrade_to_template(col, v, ctx)


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
}
