"""Tests for stateless repair strategies (Section 5.3)."""

from __future__ import annotations

from types import SimpleNamespace

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


def test_coerce_float_to_int_rewrites_random_float_to_integer():
    """The rewrite target MUST be a real core generator.

    ``random_int`` is only an expression function (SAFE_FUNCTIONS), not a
    generator in core's GENERATOR_MAP — emitting it crashes the fill with
    UnknownGeneratorError. Pin the target to ``integer``.
    """
    from sqlseed.generators._dispatch import GeneratorDispatchMixin

    col = {
        "name": "hours",
        "generator": "random_float",
        "params": {"min_value": 0, "max_value": 8},
    }
    v = _v("coerce_float_to_int")
    result = REPAIR_STRATEGIES["coerce_float_to_int"](col, v, {})
    assert result["generator"] == "integer"
    assert result["generator"] in GeneratorDispatchMixin.GENERATOR_MAP


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


# === Task 2.1: Rule #15 bound_regex tests ===
def test_bound_regex_strategy_bounds_unbounded_quantifier():
    """Rule #15: {N,} → {N,N+5} in pattern generator params."""
    from sqlseed_ai.repair.strategies import _bound_regex

    col = {
        "name": "sku",
        "generator": "pattern",
        "params": {"regex": r"^[A-Z]{3,}-\d{4,}$"},
    }
    v = ViolationReport(
        table="t",
        columns=["sku"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="bound_regex",
        fix_params={},
    )
    result = _bound_regex(col, v, {})
    assert result["params"]["regex"] == r"^[A-Z]{3,8}-\d{4,9}$"


def test_bound_regex_strategy_no_change_for_already_bounded():
    """Rule #15: no-op when quantifier is already bounded {N,M}."""
    from sqlseed_ai.repair.strategies import _bound_regex

    col = {
        "name": "code",
        "generator": "pattern",
        "params": {"regex": r"^\d{3,5}$"},
    }
    v = ViolationReport(
        table="t",
        columns=["code"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="bound_regex",
        fix_params={},
    )
    result = _bound_regex(col, v, {})
    assert result["params"]["regex"] == r"^\d{3,5}$"


# === Task 2.2: Rule #18 cap_future_end_year tests ===
def test_cap_future_end_year_caps_unreasonable_year():
    """Rule #18: end_year=2100 → end_year=current_year+1."""
    from datetime import datetime

    from sqlseed_ai.repair.strategies import _cap_future_end_year

    col = {
        "name": "expiry",
        "generator": "date",
        "params": {"end_year": 2100},
    }
    v = ViolationReport(
        table="t",
        columns=["expiry"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="cap_future_end_year",
        fix_params={},
    )
    result = _cap_future_end_year(col, v, {})
    expected_cap = datetime.now().year + 1
    assert result["params"]["end_year"] == expected_cap


def test_cap_future_end_year_noop_for_reasonable_year():
    """Rule #18: no-op when end_year <= current_year+1."""
    from datetime import datetime

    from sqlseed_ai.repair.strategies import _cap_future_end_year

    reasonable = datetime.now().year + 1
    col = {
        "name": "expiry",
        "generator": "date",
        "params": {"end_year": reasonable},
    }
    v = ViolationReport(
        table="t",
        columns=["expiry"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="cap_future_end_year",
        fix_params={},
    )
    result = _cap_future_end_year(col, v, {})
    assert result["params"]["end_year"] == reasonable


# === Task 2.3: Rule #25 downgrade_text_to_string tests ===
def test_downgrade_text_to_string_for_code_like_unique_column():
    """Rule #25: text → string for UNIQUE code-like columns (e.g., product_code)."""
    from sqlseed_ai.repair.strategies import _downgrade_text_to_string

    col = {
        "name": "product_code",
        "generator": "text",
        "params": {"max_length": 200},
    }
    v = ViolationReport(
        table="t",
        columns=["product_code"],
        constraint_type=ConstraintType.UNIQUE,
        severity="unique_unsatisfiable",
        fix_hint="downgrade_text_to_string",
        fix_params={},
    )
    result = _downgrade_text_to_string(col, v, ctx={"constraints": frozenset({"UNIQUE"})})
    assert result["generator"] == "string"
    assert "max_length" in result["params"]
    assert result["params"]["max_length"] <= 50


def test_downgrade_text_to_string_noop_for_non_code_column():
    """Rule #25: no-op for text on description-like columns."""
    from sqlseed_ai.repair.strategies import _downgrade_text_to_string

    col = {
        "name": "description",
        "generator": "text",
        "params": {"max_length": 500},
    }
    v = ViolationReport(
        table="t",
        columns=["description"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="downgrade_text_to_string",
        fix_params={},
    )
    result = _downgrade_text_to_string(col, v, ctx={"constraints": frozenset()})
    assert result["generator"] == "text"


# === Task 2.4: Rule #23 upgrade_phone_to_pattern tests ===
def test_upgrade_phone_to_pattern_for_phone_generator():
    """Rule #23: bare phone generator → pattern with NANP regex."""
    from sqlseed_ai.repair.strategies import _upgrade_phone_to_pattern

    col = {"name": "phone", "generator": "phone", "params": {}}
    v = ViolationReport(
        table="t",
        columns=["phone"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="upgrade_phone_to_pattern",
        fix_params={},
    )
    result = _upgrade_phone_to_pattern(col, v, {})
    assert result["generator"] == "pattern"
    assert result["params"]["regex"] == r"^\+1-[2-9]\d{2}-[2-9]\d{2}-\d{4}$"


def test_upgrade_phone_to_pattern_for_phone_named_string_column():
    """Rule #23: string on 'mobile' column → pattern with NANP regex."""
    from sqlseed_ai.repair.strategies import _upgrade_phone_to_pattern

    col = {"name": "mobile", "generator": "string", "params": {"max_length": 20}}
    v = ViolationReport(
        table="t",
        columns=["mobile"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="upgrade_phone_to_pattern",
        fix_params={},
    )
    result = _upgrade_phone_to_pattern(col, v, {})
    assert result["generator"] == "pattern"


def test_upgrade_phone_to_pattern_noop_for_non_phone_column():
    """Rule #23: no-op for non-phone-like column names."""
    from sqlseed_ai.repair.strategies import _upgrade_phone_to_pattern

    col = {"name": "username", "generator": "string", "params": {}}
    v = ViolationReport(
        table="t",
        columns=["username"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="upgrade_phone_to_pattern",
        fix_params={},
    )
    result = _upgrade_phone_to_pattern(col, v, {})
    assert result["generator"] == "string"


# === Blind-spot fix (2026-08-30): LENGTH CHECK no-op in upgrade_phone_to_pattern ===


def test_upgrade_phone_to_pattern_with_length_check_uses_digits_regex():
    """Rule #23: phone + LENGTH(phone)=11 → pattern [0-9]{11}, NOT a skip.

    Found live via sqlseed-web heal lab: the strategy detected the LENGTH
    CHECK and returned the column unchanged (assuming CHECK inference had
    already handled it), while the executor still recorded an AppliedFix
    with before == after — a no-op reported as a successful repair. The
    ``phone`` generator emits 19-char zh_CN mobiles (``+86 XXX-XXXXXXXX``)
    that violate ``LENGTH(phone) = 11``.

    Mirrors the 2026-07-09 blind-spot fix in ``_semantic_upgrade``: use
    ``_extract_length_check`` and upgrade to ``pattern`` with an N-digit
    regex instead of skipping.
    """
    from sqlseed_ai.repair.strategies import _upgrade_phone_to_pattern

    col = {"name": "phone", "generator": "phone", "params": {}}
    v = _v("upgrade_phone_to_pattern", columns=["phone"])
    ctx = {
        "table_schema": SimpleNamespace(
            constraints=[
                {"type": "check", "expression": "phone IS NULL OR LENGTH(phone) = 11"},
            ]
        )
    }
    result = _upgrade_phone_to_pattern(col, v, ctx)
    assert result["generator"] == "pattern"
    assert result["params"]["regex"] == "[0-9]{11}"
    # NANP regex would violate LENGTH=11 — must not be used here.
    assert "+1" not in result["params"]["regex"]


def test_upgrade_phone_to_pattern_with_length_check_on_string_col():
    """Rule #23: string on phone-like col + LENGTH CHECK → pattern [0-9]{N}.

    The LENGTH-aware upgrade applies regardless of the incoming generator
    (phone / string / pattern): NANP output is always 14 chars and would
    violate the constraint.
    """
    from sqlseed_ai.repair.strategies import _upgrade_phone_to_pattern

    col = {"name": "mobile", "generator": "string", "params": {"min_length": 11, "max_length": 11}}
    v = _v("upgrade_phone_to_pattern", columns=["mobile"])
    ctx = {
        "table_schema": SimpleNamespace(
            constraints=[
                {"type": "check", "expression": "LENGTH(mobile) = 10"},
            ]
        )
    }
    result = _upgrade_phone_to_pattern(col, v, ctx)
    assert result["generator"] == "pattern"
    assert result["params"]["regex"] == "[0-9]{10}"


# === Task 2.5: Rule #32 coerce_to_boolean_enum tests ===
def test_coerce_to_boolean_enum_for_zero_one_check():
    """Rule #32: integer column with CHECK(x IN (0,1)) → boolean generator."""
    from sqlseed_ai.repair.strategies import _coerce_to_boolean_enum

    col = {"name": "is_active", "generator": "integer", "params": {"min_value": 0, "max_value": 100}}
    v = ViolationReport(
        table="t",
        columns=["is_active"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="coerce_to_boolean_enum",
        fix_params={"check_values": [0, 1]},
    )
    result = _coerce_to_boolean_enum(col, v, {})
    assert result["generator"] == "boolean"


def test_coerce_to_boolean_enum_for_true_false_string_check():
    """Rule #32: text column with CHECK(x IN ('true','false')) → choice."""
    from sqlseed_ai.repair.strategies import _coerce_to_boolean_enum

    col = {"name": "enabled", "generator": "string", "params": {}}
    v = ViolationReport(
        table="t",
        columns=["enabled"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="coerce_to_boolean_enum",
        fix_params={"check_values": ["true", "false"]},
    )
    result = _coerce_to_boolean_enum(col, v, {})
    assert result["generator"] == "choice"
    assert result["params"]["choices"] == ["true", "false"]


# === Task 2.6: Rule #17 handle_boolean_derive tests ===
def test_handle_boolean_derive_strips_derive_from_on_boolean_column():
    """Rule #17: boolean column with derive_from → strip derive_from, set boolean gen."""
    from sqlseed_ai.repair.strategies import _handle_boolean_derive

    col = {
        "name": "is_active",
        "derive_from": "status",
        "expression": "value == 'active'",
    }
    v = ViolationReport(
        table="t",
        columns=["is_active"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="handle_boolean_derive",
        fix_params={"check_values": [0, 1]},
    )
    result = _handle_boolean_derive(col, v, {})
    assert result["generator"] == "boolean"
    assert result.get("derive_from") is None
    assert result.get("expression") is None


# === Task 2.7: Rule #33 coerce_to_text_enum tests ===
def test_coerce_to_text_enum_for_string_check_constraint():
    """Rule #33: text column with CHECK(x IN ('draft','published','archived')) → choice."""
    from sqlseed_ai.repair.strategies import _coerce_to_text_enum

    col = {"name": "status", "generator": "string", "params": {}}
    v = ViolationReport(
        table="t",
        columns=["status"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="coerce_to_text_enum",
        fix_params={"check_values": ["draft", "published", "archived"]},
    )
    result = _coerce_to_text_enum(col, v, {})
    assert result["generator"] == "choice"
    assert result["params"]["choices"] == ["draft", "published", "archived"]


def test_coerce_to_text_enum_noop_for_int_check_values():
    """Rule #33: no-op when check_values are integers (handled by Rule #32)."""
    from sqlseed_ai.repair.strategies import _coerce_to_text_enum

    col = {"name": "count", "generator": "integer", "params": {}}
    v = ViolationReport(
        table="t",
        columns=["count"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="coerce_to_text_enum",
        fix_params={"check_values": [1, 2, 3]},
    )
    result = _coerce_to_text_enum(col, v, {})
    assert result["generator"] == "integer"  # unchanged


# === Task 2.8: Rule #27 infer_derive_from_check tests ===
def test_infer_derive_from_check_for_date_range():
    """Rule #27: CHECK(end_date >= start_date) → end_date derive_from start_date."""
    from sqlseed_ai.repair.strategies import _infer_derive_from_check

    col = {"name": "end_date", "generator": "date", "params": {}}
    v = ViolationReport(
        table="t",
        columns=["end_date"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="infer_derive_from_check",
        fix_params={"source_col": "start_date", "expression": "value + timedelta(days=7)"},
    )
    result = _infer_derive_from_check(col, v, {})
    assert result["derive_from"] == "start_date"
    assert result["expression"] == "value + timedelta(days=7)"
    assert "generator" not in result or result.get("generator") is None


# === Task 2.9: Rule #31 strip_composite_unique tests ===
def test_strip_composite_unique_removes_unique_flag():
    """Rule #31: strip constraints.unique:true from composite-only columns."""
    from sqlseed_ai.repair.strategies import _strip_composite_unique

    col = {
        "name": "tenant_id",
        "generator": "integer",
        "params": {},
        "constraints": {"unique": True},
    }
    v = ViolationReport(
        table="t",
        columns=["tenant_id"],
        constraint_type=ConstraintType.UNIQUE,
        severity="semantic_error",
        fix_hint="strip_composite_unique",
        fix_params={},
    )
    result = _strip_composite_unique(col, v, {})
    assert "unique" not in result.get("constraints", {}) or not result["constraints"]["unique"]


# === Task 2.10: Rule #34 align_check_bounds tests ===
def test_align_check_bounds_strips_violating_params():
    """Rule #34: CHECK(price <= 1000) → strip max_value > 1000."""
    from sqlseed_ai.repair.strategies import _align_check_bounds

    col = {"name": "price", "generator": "random_float", "params": {"min_value": 0, "max_value": 99999}}
    v = ViolationReport(
        table="t",
        columns=["price"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="align_check_bounds",
        fix_params={"max_value": 1000},
    )
    result = _align_check_bounds(col, v, {})
    assert result["params"]["max_value"] == 1000


def test_align_check_bounds_sets_min_value():
    """Rule #34: CHECK(balance >= 0) → set min_value=0."""
    from sqlseed_ai.repair.strategies import _align_check_bounds

    col = {"name": "balance", "generator": "random_float", "params": {"min_value": -100, "max_value": 100}}
    v = ViolationReport(
        table="t",
        columns=["balance"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="align_check_bounds",
        fix_params={"min_value": 0},
    )
    result = _align_check_bounds(col, v, {})
    assert result["params"]["min_value"] == 0


# === Task 2.11: Rule #35 strip_generator_from_derive_from tests ===
def test_strip_generator_from_derive_from_removes_generator():
    """Rule #35: derive_from set + generator set → strip generator/params."""
    from sqlseed_ai.repair.strategies import _strip_generator_from_derive_from

    col = {
        "name": "total",
        "generator": "integer",
        "params": {"min_value": 0},
        "derive_from": "subtotal",
        "expression": "value * 1.1",
    }
    v = ViolationReport(
        table="t",
        columns=["total"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="strip_generator_from_derive_from",
        fix_params={},
    )
    result = _strip_generator_from_derive_from(col, v, {})
    assert "generator" not in result
    assert "params" not in result
    assert result["derive_from"] == "subtotal"
    assert result["expression"] == "value * 1.1"


# === Task 2.12: Rule #36 strip_invalid_date_derive_from tests ===
def test_strip_invalid_date_derive_from_strips_non_timedelta_expression():
    """Rule #36: date column with non-timedelta derive_from → strip derive_from."""
    from sqlseed_ai.repair.strategies import _strip_invalid_date_derive_from

    col = {
        "name": "executed_at",
        "generator": "datetime",
        "derive_from": "created_at",
        "expression": "value + random_float(0, value)",
    }
    v = ViolationReport(
        table="t",
        columns=["executed_at"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="strip_invalid_date_derive_from",
        fix_params={"is_date_column": True},
    )
    result = _strip_invalid_date_derive_from(col, v, {})
    assert "derive_from" not in result or result["derive_from"] is None
    assert "expression" not in result or result["expression"] is None
    # Generator should remain (or be reset to date/datetime)
    assert result.get("generator") in ("date", "datetime", None)


def test_strip_invalid_date_derive_from_keeps_timedelta_expression():
    """Rule #36: no-op when expression contains timedelta."""
    from sqlseed_ai.repair.strategies import _strip_invalid_date_derive_from

    col = {
        "name": "end_date",
        "generator": "date",
        "derive_from": "start_date",
        "expression": "value + timedelta(days=7)",
    }
    v = ViolationReport(
        table="t",
        columns=["end_date"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        fix_hint="strip_invalid_date_derive_from",
        fix_params={"is_date_column": True},
    )
    result = _strip_invalid_date_derive_from(col, v, {})
    assert result["derive_from"] == "start_date"
    assert result["expression"] == "value + timedelta(days=7)"


# === Blind-spot fix (2026-07-09): _semantic_upgrade phone + LENGTH CHECK ===


def test_semantic_upgrade_phone_with_length_check_uses_pattern():
    """_semantic_upgrade: phone column + LENGTH(phone)=11 → pattern [0-9]{11}.

    When the contract matrix flags ``string`` on ``phone`` as a semantic
    error, ``_semantic_upgrade`` should check for a LENGTH CHECK constraint.
    If present, upgrade to ``pattern`` with ``[0-9]{N}`` instead of ``phone``
    (which produces variable-length output that would violate LENGTH).
    """
    from sqlseed_ai.repair.strategies import _semantic_upgrade

    col = {"name": "phone", "generator": "string", "params": {"min_length": 11, "max_length": 11}}
    v = _v("semantic_upgrade")
    ctx = {
        "table_schema": SimpleNamespace(
            constraints=[
                {"type": "check", "expression": "phone IS NULL OR LENGTH(phone) = 11"},
            ]
        )
    }
    result = _semantic_upgrade(col, v, ctx)
    assert result["generator"] == "pattern"
    assert result["params"]["regex"] == "[0-9]{11}"


def test_semantic_upgrade_phone_without_length_check_uses_phone():
    """_semantic_upgrade: phone column without LENGTH CHECK → phone generator.

    When there's no LENGTH constraint, the ``phone`` generator is safe to use
    (no length violation risk). The upgrade proceeds normally.
    """
    from sqlseed_ai.repair.strategies import _semantic_upgrade

    col = {"name": "phone", "generator": "string", "params": {"max_length": 20}}
    v = _v("semantic_upgrade")
    ctx = {"table_schema": SimpleNamespace(constraints=[])}
    result = _semantic_upgrade(col, v, ctx)
    assert result["generator"] == "phone"
    assert "params" not in result


def test_semantic_upgrade_email_still_drops_params():
    """_semantic_upgrade: email column → email generator (params dropped).

    Non-phone columns are unaffected by the LENGTH CHECK fix. The ``email``
    generator doesn't use length params, so dropping them is correct.
    """
    from sqlseed_ai.repair.strategies import _semantic_upgrade

    col = {"name": "user_email", "generator": "string", "params": {"min_length": 5}}
    v = _v("semantic_upgrade")
    result = _semantic_upgrade(col, v, {})
    assert result["generator"] == "email"
    assert "params" not in result
