"""Tests for validator data models (Section 4.2)."""
from __future__ import annotations

from sqlseed_ai.validator.models import (
    ColumnGroup,
    ConstraintType,
    ValidationResult,
    ViolationReport,
)


def test_violation_report_defaults():
    v = ViolationReport(
        table="users", columns=["email"],
        constraint_type=ConstraintType.UNIQUE,
        severity="crash",
    )
    assert v.raw_expression is None
    assert v.constraint_name is None
    assert v.is_composite is False
    assert v.fix_hint is None
    assert v.fix_params == {}
    assert v.source == "validation"
    assert v.message is None


def test_column_group_defaults():
    g = ColumnGroup(
        group_id="orders_shop_user_fk",
        columns=["shop_id", "user_id"],
        parent_table="shop_users",
        parent_columns=["shop_id", "user_id"],
    )
    assert g.degrade_together is True


def test_validation_result_is_clean_flag():
    clean = ValidationResult(violations=[], column_groups=[])
    assert clean.is_clean is True
    dirty = ValidationResult(
        violations=[ViolationReport(
            table="t", columns=["c"],
            constraint_type=ConstraintType.CHECK, severity="crash",
        )],
        column_groups=[],
    )
    assert dirty.is_clean is False


def test_violation_report_message_field():
    """Adversarial fix (C3): message field exists for LLMHealer prompt building."""
    v = ViolationReport(
        table="t", columns=["c"],
        constraint_type=ConstraintType.CHECK, severity="crash",
        message="CHECK constraint failed: price >= 0",
    )
    assert v.message == "CHECK constraint failed: price >= 0"
