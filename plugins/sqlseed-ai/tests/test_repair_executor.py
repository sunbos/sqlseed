"""Tests for RepairExecutor (Section 5.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlseed_ai.repair.executor import RepairExecutor
from sqlseed_ai.repair.strategies import REPAIR_STRATEGIES
from sqlseed_ai.validator.models import ConstraintType, ViolationReport

from tests.assertions import assert_empty

if TYPE_CHECKING:
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


def test_executor_repairs_integer_on_timestamp(timestamp_snapshot: SchemaSnapshot):
    config = {
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "created_at", "generator": "integer"},
                ],
            }
        ]
    }
    violations = [
        ViolationReport(
            table="t",
            columns=["created_at"],
            constraint_type=ConstraintType.CHECK,
            severity="crash",
            fix_hint="switch_generator",
            fix_params={"target": "datetime"},
        )
    ]
    executor = RepairExecutor(REPAIR_STRATEGIES)
    result = executor.repair(config, violations, timestamp_snapshot)
    assert result.fix_count == 1
    fixed_col = next(c for c in config["tables"][0]["columns"] if c["name"] == "created_at")
    assert fixed_col["generator"] == "datetime"


def test_executor_skips_unknown_strategy(timestamp_snapshot: SchemaSnapshot):
    config = {"tables": [{"name": "t", "columns": [{"name": "x", "generator": "string"}]}]}
    violations = [
        ViolationReport(
            table="t",
            columns=["x"],
            constraint_type=ConstraintType.CHECK,
            severity="crash",
            fix_hint="nonexistent_strategy",
        )
    ]
    executor = RepairExecutor(REPAIR_STRATEGIES)
    result = executor.repair(config, violations, timestamp_snapshot)
    assert len(result.unfixable) == 1
    assert result.fix_count == 0


def test_executor_sorts_by_severity_crash_first(timestamp_snapshot: SchemaSnapshot):
    """CRASH severity repaired before SEMANTIC_ERROR."""
    config = {
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "a", "generator": "integer"},
                    {"name": "b", "generator": "float"},
                ],
            }
        ]
    }
    violations = [
        ViolationReport(
            table="t",
            columns=["b"],
            constraint_type=ConstraintType.CHECK,
            severity="semantic_error",
            fix_hint="switch_generator",
            fix_params={"target": "string"},
        ),
        ViolationReport(
            table="t",
            columns=["a"],
            constraint_type=ConstraintType.CHECK,
            severity="crash",
            fix_hint="switch_generator",
            fix_params={"target": "string"},
        ),
    ]
    executor = RepairExecutor(REPAIR_STRATEGIES)
    result = executor.repair(config, violations, timestamp_snapshot)
    assert result.fix_count == 2
    # CRASH (a) should be fixed first
    assert result.applied_fixes[0].columns == ["a"]


# === Blind-spot fix (2026-08-30): no-op strategies reported as successful fixes ===


def test_executor_does_not_record_noop_fix_as_applied(timestamp_snapshot: SchemaSnapshot):
    """A strategy that returns the column unchanged is NOT a successful fix.

    Found live via sqlseed-web heal lab: ``upgrade_phone_to_pattern`` on a
    non-phone-like column returns the column unchanged, yet the executor
    appended an ``AppliedFix`` with ``before == after`` — inflating
    fix_count and breaking the pipeline's partial-fix re-validation
    heuristic (``len(applied_fixes) < len(violations)``).

    Expected accounting: unchanged column → violation goes to ``unfixable``,
    no AppliedFix, config untouched.
    """
    config = {"tables": [{"name": "t", "columns": [{"name": "note", "generator": "string"}]}]}
    violations = [
        ViolationReport(
            table="t",
            columns=["note"],
            constraint_type=ConstraintType.CHECK,
            severity="semantic_error",
            fix_hint="upgrade_phone_to_pattern",
        )
    ]
    executor = RepairExecutor(REPAIR_STRATEGIES)
    result = executor.repair(config, violations, timestamp_snapshot)
    assert result.fix_count == 0
    assert_empty(result.applied_fixes, list)
    assert len(result.unfixable) == 1
    assert result.unfixable[0].columns == ["note"]
    # Config untouched — the strategy declined to modify the column.
    assert config["tables"][0]["columns"][0] == {"name": "note", "generator": "string"}
