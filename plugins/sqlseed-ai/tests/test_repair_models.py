"""Tests for repair data structures (Section 5.2)."""

from __future__ import annotations

from sqlseed_ai.repair.models import AppliedFix, RepairResult


def test_applied_fix_defaults():
    fix = AppliedFix(
        table="users",
        columns=["email"],
        fix_strategy="switch_generator",
        before={"generator": "integer"},
        after={"generator": "string"},
        violation_kind="crash",
    )
    assert fix.success is True


def test_repair_result_fix_count():
    fix = AppliedFix(
        table="t",
        columns=["c"],
        fix_strategy="switch_generator",
        before={},
        after={},
        violation_kind="crash",
    )
    result = RepairResult(config={"tables": []}, applied_fixes=[fix], unfixable=[])
    assert result.fix_count == 1
