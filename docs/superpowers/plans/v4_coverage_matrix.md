# v4 Coverage Matrix

**Date:** 2026-07-07 (updated post-Phase 4)
**Method:** Static code analysis of legacy rule inventory + v4 `REPAIR_STRATEGIES` dict.
**Status:** All 36 legacy rule scenarios covered by v4. Legacy source files deleted in Phase 4 zero-rot cleanup.

## Source of Truth (Current)

- `plugins/sqlseed-ai/src/sqlseed_ai/repair/strategies.py` — `REPAIR_STRATEGIES` dict (25 stateless strategies)
- `plugins/sqlseed-ai/src/sqlseed_ai/contracts/builtin_violations.py` — 23 builtin `ContractViolation` entries
- `plugins/sqlseed-ai/src/sqlseed_ai/validator/` — `FastValidator` + `SingleColumnValidator` + `CrossColumnValidator`

> **Note:** The following legacy source files were deleted in Phase 4 and are no longer present:
> - `staged_analyzer.py` (contained `Stage3Validator` + rules #14-#36)
> - `schema_analyzer.py` (contained `apply_auto_fix_rules_1_13()`)
> - `repair/legacy_bridge.py` (contained `RULE_MAPPING`)
>
> This document preserves the rule-to-strategy mapping for audit purposes.

## Rule Classification

### Rules #1-#13 (formerly in `apply_auto_fix_rules_1_13()` — DELETED)

These were early-cycle fixes applied before `Stage3Validator` ran. They overlapped with v4's strategies (e.g., Fix #1 mutual exclusivity == Rule #35; Fix #14 param whitelist == `normalize_params`). Phase 4 deleted `apply_auto_fix_rules_1_13()` entirely; v4's contract matrix + validator + strategies cover the same scenarios declaratively.

| Rule # | Fix Description | v4 Coverage | Notes |
|--------|----------------|-------------|-------|
| #1 | derive_from wins mutual exclusivity | ✅ `strip_generator_from_derive_from` (Rule #35 migration) | Same scenario as Rule #35 |
| #2-#13 | Various inline fixes | ✅ Covered by v4 contract matrix + 25 strategies | Declarative detection + stateless repair |

### Rules #14-#30 (formerly in `Stage3Validator` — DELETED)

| Rule # | Strategy Name | v4 Strategy | Status | Notes |
|--------|---------------|-------------|--------|-------|
| #14 | normalize_params | `_normalize_params` | ✅ Migrated | Refiner delegates to `REPAIR_STRATEGIES["normalize_params"]`; 36-entry whitelist |
| #15 | bound_regex | `_bound_regex` | ✅ Migrated (Phase 2 Task 2.1) | + `ContractViolation` entry |
| #16 | align_fk_max_value | `_align_fk_max_value` | ✅ Pre-existing | Table-level rule |
| #17 | handle_boolean_derive | `_handle_boolean_derive` | ✅ Migrated (Phase 2 Task 2.6) | |
| #18 | limit_future_year | `_cap_future_end_year` | ✅ Migrated (Phase 2 Task 2.2) | + `ContractViolation` entry |
| #19 | adjust_bounds | `_adjust_bounds` | ✅ Pre-existing | Table-level rule |
| #20 | fix_self_reference | `_fix_self_reference` | ✅ Pre-existing | |
| #22 | isolate_date_ranges | `_isolate_date_ranges` | ✅ Pre-existing | Table-level rule; deferred `_has_date_year_range` check runs after derive_from processing |
| #23 | upgrade_phone_to_pattern | `_upgrade_phone_to_pattern` | ✅ Migrated (Phase 2 Task 2.4) | + `ContractViolation` entry |
| #24 | upgrade_to_template | `_upgrade_to_template` | ✅ Pre-existing | |
| #25 | downgrade_text_to_string | `_downgrade_text_to_string` | ✅ Migrated (Phase 2 Task 2.3) | + `ContractViolation` entry |
| #26 | coerce_float_to_int | `_coerce_float_to_int` | ✅ Pre-existing | INTEGER column coercion |
| #27 | infer_derive_from_check | `_infer_derive_from_check` | ✅ Migrated (Phase 2 Task 2.8) | CHECK chain mirroring (Case 1 + Case 2) |
| #28 | semantic_upgrade | `_semantic_upgrade` | ✅ Pre-existing | |
| #29 | break_derive_from_cycle | `_break_derive_from_cycle` | ✅ Pre-existing | Table-level rule |
| #30 | switch_generator | `_switch_generator` | ✅ Pre-existing | |

Note: Rule #21 never existed (confirmed in former `legacy_bridge.py` docstring).

### Rules #31-#36 (formerly in `Stage3Validator` — DELETED)

These rules were added in Loop Engineering Phase 7-8. They have been migrated to v4 in Phase 2.

| Rule # | Method Name | v4 Strategy | Status | Notes |
|--------|-------------|-------------|--------|-------|
| #31 | `_apply_rule_31_strip_composite_unique` | `_strip_composite_unique` | ✅ Migrated (Phase 2 Task 2.9) | + validator `_check_composite_unique` detection |
| #32 | `_apply_rule_32_boolean_enum_check` | `_coerce_to_boolean_enum` | ✅ Migrated (Phase 2 Task 2.5) | |
| #33 | `_apply_rule_33_text_enum_check` | `_coerce_to_text_enum` | ✅ Migrated (Phase 2 Task 2.7) | |
| #34 | `_apply_rule_34_cross_column_numeric_check` | `_align_check_bounds` | ✅ Migrated (Phase 2 Task 2.10) | + `CrossColumnValidator` CHECK constraint detection |
| #35 | `_apply_rule_35_strip_generator_from_derive_from` | `_strip_generator_from_derive_from` | ✅ Migrated (Phase 2 Task 2.11) | |
| #36 | `_apply_rule_36_strip_invalid_date_derive_from_expression` | `_strip_invalid_date_derive_from` | ✅ Migrated (Phase 2 Task 2.12) | + `_ensure_date_generator_for_date_column` |

## Summary (Post-Phase 4 — All Complete)

| Category | Count | Rules |
|----------|-------|-------|
| ✅ Already covered by v4 (pre-existing) | 10 | #14, #16, #19, #20, #22, #24, #26, #28, #29, #30 |
| ✅ Migrated in Phase 2 | 12 | #15, #17, #18, #23, #25, #27, #31, #32, #33, #34, #35, #36 |
| Total Stage3Validator rules | 22 | #14-#20, #22-#36 (no #21) |
| Rules #1-#13 | 13 | Covered by v4 declaratively; `apply_auto_fix_rules_1_13()` deleted in Phase 4 |

**Phase 2 Status: COMPLETE** — All 12 previously-uncovered rules now have v4 stateless strategies + tests passing.

**Phase 4 Status: COMPLETE** — All legacy source files deleted (zero dead code verified). `REPAIR_STRATEGIES` dict contains 25 entries (13 original + 12 migrated). Full test suite (1954 tests), ruff, mypy, architecture guards, and doc sync all pass.

## Phase 2 Migration History (Completed)

12 rules migrated in 14 tasks (Task 2.1-2.14):
- Task 2.1: Rule #15 → `_bound_regex` ✅
- Task 2.2: Rule #18 → `_cap_future_end_year` ✅
- Task 2.3: Rule #25 → `_downgrade_text_to_string` ✅
- Task 2.4: Rule #23 → `_upgrade_phone_to_pattern` ✅
- Task 2.5: Rule #32 → `_coerce_to_boolean_enum` ✅
- Task 2.6: Rule #17 → `_handle_boolean_derive` ✅
- Task 2.7: Rule #33 → `_coerce_to_text_enum` ✅
- Task 2.8: Rule #27 → `_infer_derive_from_check` ✅
- Task 2.9: Rule #31 → `_strip_composite_unique` + validator detection ✅
- Task 2.10: Rule #34 → `_align_check_bounds` ✅
- Task 2.11: Rule #35 → `_strip_generator_from_derive_from` ✅
- Task 2.12: Rule #36 → `_strip_invalid_date_derive_from` ✅
- Task 2.13: Add ContractViolation entries for Rules #15, #18, #23, #25 ✅
- Task 2.14: Re-audit (verify all 12 rules now covered) ✅
