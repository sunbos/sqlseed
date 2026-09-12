"""Tests for CrossColumnValidator (2b) — cross-column constraint checks."""

from __future__ import annotations

from sqlseed_ai.validator.cross_column import CrossColumnValidator
from sqlseed_ai.validator.models import ConstraintType

from tests.assertions import assert_empty


def _derived_pair_config(source: str | list[str]) -> dict:
    return {
        "name": "t",
        "columns": [
            {"name": "a", "generator": "integer"},
            {"name": "b", "derive_from": source, "expression": "value + 1"},
        ],
    }


def test_check_derive_from_dag_detects_2_cycle():
    """A derives from B, B derives from A → 2-cycle violation."""
    validator = CrossColumnValidator()
    config = {
        "name": "t",
        "columns": [
            {"name": "a", "derive_from": ["b"], "expression": "value + 1"},
            {"name": "b", "derive_from": ["a"], "expression": "value + 2"},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []})
    assert any(v.constraint_type == ConstraintType.CHECK for v in violations)
    assert any(v.fix_hint == "break_derive_from_cycle" for v in violations)


def test_check_derive_from_dag_detects_self_reference():
    """A derives from A → self-reference violation."""
    validator = CrossColumnValidator()
    config = {
        "name": "t",
        "columns": [
            {"name": "a", "derive_from": "a", "expression": "value + 1"},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []})
    assert any(v.fix_hint == "fix_self_reference" for v in violations)


def test_check_derive_from_dag_clean_when_no_cycle():
    """No cycle → no derive_from violations."""
    validator = CrossColumnValidator()
    config = _derived_pair_config(["a"])
    violations = validator.validate(config, {"columns": [], "constraints": []})
    assert_empty(violations, list)


def test_plain_generator_has_no_cross_column_violation():
    """A plain generator does not introduce a dependency or uniqueness violation."""
    validator = CrossColumnValidator()
    config = {
        "name": "orders",
        "columns": [
            {"name": "user_id", "generator": "integer", "params": {"min_value": 0, "max_value": 99999}},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []})
    assert_empty(violations, list)


def test_no_cross_column_violation_without_table_schema():
    """Missing table metadata does not invent cross-column constraints."""
    validator = CrossColumnValidator()
    config = {
        "name": "nonexistent_table",
        "columns": [
            {"name": "user_id", "generator": "integer", "params": {"max_value": 99999}},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []})
    assert_empty(violations, list)


def test_validate_handles_string_derive_from():
    """derive_from as a string (single dep) should work, not crash."""
    validator = CrossColumnValidator()
    config = _derived_pair_config("a")
    violations = validator.validate(config, {"columns": [], "constraints": []})
    # No cycle, no self-reference → no violations
    assert_empty(violations, list)


def test_check_composite_unique_flags_individually_unique_composite_col():
    """Rule #31: column only in composite UNIQUE should not have unique:true."""

    validator = CrossColumnValidator()
    table_config = {
        "name": "user_emails",
        "columns": [
            {"name": "tenant_id", "generator": "integer", "params": {}, "constraints": {"unique": True}},
            {"name": "email", "generator": "string", "params": {}},
        ],
    }
    table_schema = {
        "name": "user_emails",
        "columns": [
            {"name": "tenant_id", "type": "INTEGER", "nullable": False},
            {"name": "email", "type": "TEXT", "nullable": False},
        ],
        "constraints": [
            {"type": "unique", "columns": ["tenant_id", "email"]},  # composite
        ],
        "unique_indexes": [{"columns": ["tenant_id", "email"]}],
    }

    violations = validator._check_composite_unique(table_config, table_schema)
    assert len(violations) == 1
    assert violations[0].columns == ["tenant_id"]
    assert violations[0].fix_hint == "strip_composite_unique"
