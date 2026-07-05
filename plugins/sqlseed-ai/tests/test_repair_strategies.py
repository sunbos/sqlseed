"""Tests for stateless repair strategies (Section 5.3)."""
from __future__ import annotations

from sqlseed_ai.repair.strategies import REPAIR_STRATEGIES
from sqlseed_ai.validator.models import ConstraintType, ViolationReport


def _v(fix_hint: str, fix_params: dict | None = None, columns: list[str] | None = None) -> ViolationReport:
    return ViolationReport(
        table="t",
        columns=columns or ["c"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint=fix_hint,
        fix_params=fix_params or {},
    )


def test_switch_generator_replaces_generator_and_strips_params():
    col = {"name": "created_at", "generator": "integer", "params": {"min_value": 0}}
    v = _v("switch_generator", {"target": "datetime"})
    result = REPAIR_STRATEGIES["switch_generator"](col, v, {})
    assert result["generator"] == "datetime"
    assert "params" not in result


def test_switch_generator_to_string_invokes_semantic_upgrade():
    """Adversarial fix (C5): switching to 'string' should attempt semantic
    upgrade based on column name (mirrors Spec Section 5.3 behavior)."""
    col = {"name": "user_email", "generator": "integer", "params": {}}
    v = _v("switch_generator", {"target": "string"})
    result = REPAIR_STRATEGIES["switch_generator"](col, v, {})
    # Should upgrade "string" → "email" because column name contains "email"
    assert result["generator"] == "email"


def test_switch_generator_to_string_keeps_string_when_no_pattern_matches():
    """Adversarial fix (C5): no semantic pattern match → keep 'string'."""
    col = {"name": "misc_field", "generator": "integer", "params": {}}
    v = _v("switch_generator", {"target": "string"})
    result = REPAIR_STRATEGIES["switch_generator"](col, v, {})
    assert result["generator"] == "string"


def test_upgrade_to_template_for_unique_code_column():
    col = {"name": "order_code", "generator": "string", "params": {"max_length": 10}}
    v = _v("upgrade_to_template")
    result = REPAIR_STRATEGIES["upgrade_to_template"](col, v, {})
    assert result["generator"] == "template"
    assert "template" in result["params"]
    assert result["derive_from"] is None


def test_normalize_params_wraps_choice_list():
    col = {"name": "category", "generator": "choice", "params": ["a", "b", "c"]}
    v = _v("normalize_params")
    result = REPAIR_STRATEGIES["normalize_params"](col, v, {})
    assert result["params"] == {"choices": ["a", "b", "c"]}


def test_normalize_params_fixes_choice_typo():
    col = {"name": "c", "generator": "choice", "params": {"choice": ["a", "b"]}}
    v = _v("normalize_params")
    result = REPAIR_STRATEGIES["normalize_params"](col, v, {})
    assert result["params"] == {"choices": ["a", "b"]}


def test_coerce_float_to_int_rewrites_random_float_to_random_int():
    col = {
        "name": "hours",
        "generator": "random_float",
        "params": {"min_value": 0, "max_value": 8},
    }
    v = _v("coerce_float_to_int")
    result = REPAIR_STRATEGIES["coerce_float_to_int"](col, v, {})
    assert result["generator"] == "random_int"


def test_fix_self_reference_strips_derive_from_when_self_referenced():
    col = {"name": "total", "derive_from": ["total"], "expression": "value + 1"}
    v = _v("fix_self_reference", {}, ["total"])
    result = REPAIR_STRATEGIES["fix_self_reference"](col, v, {})
    assert result.get("derive_from") is None
    assert result.get("expression") is None
    assert "generator" in result  # fallback generator assigned


def test_all_13_strategies_present():
    expected = {
        "switch_generator",
        "upgrade_to_template",
        "normalize_params",
        "break_derive_from_cycle",
        "adjust_bounds",
        "align_fk_max_value",
        "isolate_date_ranges",
        "semantic_upgrade",
        "fix_self_reference",
        "coerce_float_to_int",
        "align_group_generators",
        "expand_pool",
        "add_unique_suffix",
    }
    assert expected.issubset(set(REPAIR_STRATEGIES.keys()))
