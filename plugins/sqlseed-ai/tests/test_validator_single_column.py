"""Tests for SingleColumnValidator (2a) — sparse matrix contract check."""

from __future__ import annotations

from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
from sqlseed_ai.contracts.matrix import ContractResolver
from sqlseed_ai.validator.models import ConstraintType
from sqlseed_ai.validator.single_column import SingleColumnValidator


def _make_table_config(columns):
    return {"name": "t", "columns": columns}


def _make_schema(column_types):
    return {
        "t": {
            "columns": [{"name": n, "type": t} for n, t in column_types.items()],
            "constraints": [],
        }
    }


def test_validate_flags_integer_on_timestamp():
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    config = _make_table_config([{"name": "created_at", "generator": "integer"}])
    schema = _make_schema({"created_at": "TIMESTAMP"})
    violations = validator.validate(config, schema["t"], row_count=10)
    assert len(violations) == 1
    assert violations[0].fix_hint == "switch_generator"


def test_validate_flags_unique_choice_low_cardinality():
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    config = _make_table_config(
        [
            {
                "name": "category",
                "generator": "choice",
                "params": {"choices": ["a", "b", "c"]},
            },
        ]
    )
    schema = {
        "t": {
            "columns": [{"name": "category", "type": "TEXT"}],
            "constraints": [{"type": "unique", "columns": ["category"]}],
        }
    }
    violations = validator.validate(config, schema["t"], row_count=1000)
    assert any(v.constraint_type == ConstraintType.UNIQUE for v in violations)


def test_validate_passes_compatible_combo():
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    config = _make_table_config([{"name": "id", "generator": "integer"}])
    schema = _make_schema({"id": "INTEGER"})
    violations = validator.validate(config, schema["t"], row_count=100)
    assert violations == []


def test_compute_cardinality_choice():
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    assert validator._compute_cardinality({"generator": "choice", "params": {"choices": ["a", "b", "c"]}}, 100) == 3


def test_compute_cardinality_integer_robust_defaults():
    """Missing min/max -> robust defaults (not crash). Spec 微调3."""
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    # No params at all -> robust default
    assert validator._compute_cardinality({"generator": "integer"}, 100) == 10000
    # Only min_value -> max defaults to 9999
    assert validator._compute_cardinality({"generator": "integer", "params": {"min_value": 5}}, 100) == 9995


def test_compute_cardinality_template_infinite():
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    assert validator._compute_cardinality({"generator": "template"}, 100) == float("inf")


def test_compute_cardinality_string():
    """String cardinality = 62^max_length (default 10)."""
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    # Default max_length=10
    assert validator._compute_cardinality({"generator": "string"}, 100) == 62**10
    # Custom max_length=4
    assert validator._compute_cardinality({"generator": "string", "params": {"max_length": 4}}, 100) == 62**4


def test_compute_cardinality_unknown_generator_returns_row_count():
    """Unknown generators get optimistic row_count cardinality."""
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    assert validator._compute_cardinality({"generator": "unknown_gen"}, 500) == 500


def test_validate_flags_random_float_on_integer_column():
    """Rule #26: random_float on INTEGER column should be flagged."""
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    config = _make_table_config(
        [{"name": "qty", "generator": "random_float", "params": {"min_value": 0, "max_value": 100}}]
    )
    schema = _make_schema({"qty": "INTEGER"})
    violations = validator.validate(config, schema["t"], row_count=10)
    assert any(v.fix_hint == "coerce_float_to_int" for v in violations)


def test_extract_constraints_detects_unique_and_not_null():
    """_extract_constraints should find UNIQUE from constraints and NOT_NULL from column def."""
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    table_schema = {
        "columns": [{"name": "email", "type": "TEXT", "nullable": False}],
        "constraints": [{"type": "unique", "columns": ["email"]}],
    }
    constraints = validator._extract_constraints("email", table_schema)
    assert "UNIQUE" in constraints
    assert "NOT_NULL" in constraints


def test_extract_col_type_returns_any_for_unknown_column():
    """_extract_col_type returns 'ANY' when column not found in schema."""
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = SingleColumnValidator(resolver)
    table_schema = {"columns": [{"name": "id", "type": "INTEGER"}], "constraints": []}
    assert validator._extract_col_type("nonexistent", table_schema) == "ANY"
    assert validator._extract_col_type("id", table_schema) == "INTEGER"
