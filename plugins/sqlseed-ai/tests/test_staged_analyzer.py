"""Tests for staged_analyzer module."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlseed_ai.staged_analyzer import (
    ErrorCategory,
    ErrorClassifier,
    StructureSummary,
    TableStructureSummary,
)

from sqlseed.core.features import (
    ColumnFeatures,
    ForeignKeyFeatures,
    StructuralFeatures,
    TableFeatures,
)


def test_table_structure_summary_minimal():
    """TableStructureSummary requires name/purpose/anchor_columns/naming_prefix/complexity."""
    summary = TableStructureSummary(
        name="users",
        purpose="User account management",
        anchor_columns=["id", "email"],
        naming_prefix="USER-",
        complexity=10,
    )
    assert summary.name == "users"
    assert summary.cross_column_checks == []
    assert summary.fk_references == []


def test_structure_summary_has_required_fields():
    """StructureSummary has schema_hash/topological_order/fk_graph/tables/etc."""
    summary = StructureSummary(
        schema_hash="abc123",
        topological_order=["users", "orders"],
        fk_graph=[{"parent": "users", "child": "orders", "col": "user_id"}],
        tables=[],
        naming_conventions={"users": "USER-", "orders": "ORD-"},
        complexity_score={"tables": 2, "avg_columns": 5, "avg_constraints": 2},
        dialect="sqlite",
    )
    assert summary.schema_hash == "abc123"
    assert summary.topological_order == ["users", "orders"]
    assert summary.dialect == "sqlite"


def test_error_classifier_transient_timeout():
    """TimeoutError classified as TRANSIENT."""
    category = ErrorClassifier.classify(TimeoutError("LLM timeout"))
    assert category == ErrorCategory.TRANSIENT


def test_error_classifier_logic_json_decode():
    """JSON decode error classified as LOGIC."""
    import json

    try:
        json.loads("{invalid}")
    except json.JSONDecodeError as e:
        category = ErrorClassifier.classify(e)
        assert category == ErrorCategory.LOGIC


def test_error_classifier_quality_empty_output():
    """Empty output classified as QUALITY."""
    category = ErrorClassifier.classify(RuntimeError("empty"), output="")
    assert category == ErrorCategory.QUALITY


def test_error_classifier_quality_short_output():
    """Short output (<50 chars) classified as QUALITY."""
    category = ErrorClassifier.classify(RuntimeError("too short"), output='{"name":"t"}')
    assert category == ErrorCategory.QUALITY


def test_error_classifier_quality_all_string_default():
    """Output with >80% string generators classified as QUALITY (LLM gave up)."""
    output = '{"columns":[{"name":"a","generator":"string"},{"name":"b","generator":"string"}]}'
    category = ErrorClassifier.classify(RuntimeError("all defaults"), output=output)
    assert category == ErrorCategory.QUALITY


def _make_simple_features() -> StructuralFeatures:
    """Build minimal StructuralFeatures for staged analyzer tests."""
    users = TableFeatures(
        name="users",
        columns=[
            ColumnFeatures(
                name="id",
                type="INTEGER",
                nullable=False,
                default=None,
                is_primary_key=True,
                is_autoincrement=True,
                is_computed=False,
            ),
            ColumnFeatures(
                name="email",
                type="TEXT",
                nullable=False,
                default=None,
                is_primary_key=False,
                is_autoincrement=False,
                is_computed=False,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        unique_constraints=[],
        check_constraints=[],
        indexes=[],
    )
    orders = TableFeatures(
        name="orders",
        columns=[
            ColumnFeatures(
                name="id",
                type="INTEGER",
                nullable=False,
                default=None,
                is_primary_key=True,
                is_autoincrement=True,
                is_computed=False,
            ),
            ColumnFeatures(
                name="user_id",
                type="INTEGER",
                nullable=False,
                default=None,
                is_primary_key=False,
                is_autoincrement=False,
                is_computed=False,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[
            ForeignKeyFeatures(
                table="orders",
                columns=["user_id"],
                ref_table="users",
                ref_columns=["id"],
            ),
        ],
        unique_constraints=[],
        check_constraints=[],
        indexes=[],
    )
    return StructuralFeatures(
        dialect="sqlite",
        tables=[users, orders],
        schema_hash="test123",
    )


def test_stage1_fallback_returns_deterministic_summary_when_llm_fails():
    """P3 #4: stage 1 fallback returns deterministic StructureSummary.

    When LLM returns empty/invalid output 3 times, stage 1 degrades to
    a deterministic summary derived purely from StructuralFeatures
    (no LLM). This ensures pipeline continues rather than crashes.
    """
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    features = _make_simple_features()
    analyzer = StagedSchemaAnalyzer(config=None)

    # Mock low-level analyzer to always raise (simulating LLM failure)
    mock_low_level = MagicMock()
    mock_low_level._call_llm_once.side_effect = RuntimeError("LLM unavailable")
    analyzer._low_level_analyzer = mock_low_level

    summary = analyzer._run_stage1_with_fallback(features)

    # Fallback should produce a deterministic StructureSummary
    assert isinstance(summary, StructureSummary)
    assert summary.dialect == "sqlite"
    assert summary.schema_hash == "test123"
    # Topological order: users before orders (FK dependency)
    assert summary.topological_order == ["users", "orders"]
    # Tables should have summaries with naming prefixes derived from table name
    users_summary = next(t for t in summary.tables if t.name == "users")
    assert users_summary.naming_prefix == "USER-"
    orders_summary = next(t for t in summary.tables if t.name == "orders")
    assert orders_summary.naming_prefix == "ORDE-"


def test_stage1_naming_prefix_derived_from_table_name():
    """Naming prefix derived from table name (first 4 chars upper + '-')."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    analyzer = StagedSchemaAnalyzer(config=None)
    assert analyzer._derive_naming_prefix("users") == "USER-"
    assert analyzer._derive_naming_prefix("orders") == "ORDE-"
    assert analyzer._derive_naming_prefix("categories") == "CATE-"


def test_stage1_topological_sort_orders_by_fk_dependency():
    """Topological sort puts FK parents before children."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    analyzer = StagedSchemaAnalyzer(config=None)
    features = _make_simple_features()
    order = analyzer._topological_sort(features)
    # users must come before orders (orders has FK to users)
    assert order.index("users") < order.index("orders")


def test_stage2_per_column_calls_llm_once_per_column():
    """Stage 2 per_column mode calls LLM once per non-skipped column."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    features = _make_simple_features()
    analyzer = StagedSchemaAnalyzer(config=None)

    # Mock low-level analyzer
    mock_low_level = MagicMock()
    stage2_response = '{"column":"id","generator":"integer","params":{},"derive_from":null,"expression":null}'
    mock_low_level._call_llm_once.return_value = stage2_response
    analyzer._low_level_analyzer = mock_low_level

    # Build summary
    summary = analyzer._run_stage1_with_fallback(features)

    # Reset mock to isolate Stage 2 call count (Stage 1 also calls LLM)
    mock_low_level._call_llm_once.reset_mock()

    # Run stage 2 per_column
    result = analyzer._run_stage2_per_column(features, summary, target_tables=["users"])

    # Should have called LLM for each non-skipped column
    # users has id (PK autoincrement, skipped) + email (1 call)
    assert mock_low_level._call_llm_once.call_count == 1
    assert "tables" in result
    assert len(result["tables"]) == 1
    assert result["tables"][0]["name"] == "users"


def test_stage2_per_column_strips_llm_returned_column_key():
    """Bug #3 regression: LLM returns {"column": "email", ...} but Stage 2 must
    replace it with the canonical "name" field (matched to the real column),
    not keep both. Keeping both caused Pydantic to forward "column" as a
    generator param, raising
    ``BaseProvider._gen_string() got an unexpected keyword argument 'column'``.

    This is a behavior test (not a wiring test): it verifies the *output shape*
    of the generated config dict, not the call count.
    """
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    features = _make_simple_features()
    analyzer = StagedSchemaAnalyzer(config=None)

    # Mock low-level analyzer with a response that includes the "column" key
    # (which is what the LLM actually returns; see complex_biz_staged.yaml).
    mock_low_level = MagicMock()
    stage2_response = '{"column":"email","generator":"email","params":{},"derive_from":null,"expression":null}'
    mock_low_level._call_llm_once.return_value = stage2_response
    analyzer._low_level_analyzer = mock_low_level

    summary = analyzer._run_stage1_with_fallback(features)
    mock_low_level._call_llm_once.reset_mock()

    result = analyzer._run_stage2_per_column(features, summary, target_tables=["users"])

    col_config = result["tables"][0]["columns"][0]
    # The "name" key must be present and equal the real column name
    assert col_config["name"] == "email"
    # The LLM-returned "column" key must be stripped to avoid generator param clash
    assert "column" not in col_config, f"Expected 'column' key to be stripped, got keys: {list(col_config.keys())}"


def test_stage2_per_column_skips_pk_autoincrement_columns():
    """Stage 2 skips PK/AUTOINCREMENT/GENERATED/DEFAULT columns."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    features = _make_simple_features()
    analyzer = StagedSchemaAnalyzer(config=None)

    # Should skip id (PK + autoincrement)
    skip_cols = analyzer._get_skippable_columns(next(t for t in features.tables if t.name == "users"))
    assert "id" in skip_cols
    assert "email" not in skip_cols


def test_stage2_per_column_injects_cross_column_checks_in_prompt():
    """P1 #3 fix: cross-column CHECK injected into per_column prompt."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    analyzer = StagedSchemaAnalyzer(config=None)
    # Build features with cross-column CHECK
    cross_check_table = TableFeatures(
        name="projects",
        columns=[
            ColumnFeatures(
                name="start_date",
                type="DATE",
                nullable=False,
                default=None,
                is_primary_key=False,
                is_autoincrement=False,
                is_computed=False,
            ),
            ColumnFeatures(
                name="end_date",
                type="DATE",
                nullable=False,
                default=None,
                is_primary_key=False,
                is_autoincrement=False,
                is_computed=False,
            ),
        ],
        primary_key=[],
        foreign_keys=[],
        unique_constraints=[],
        check_constraints=[],
        indexes=[],
    )
    # Manually add cross-column CHECK (since check_constraints needs CheckConstraintFeatures)
    from sqlseed.core.features import CheckConstraintFeatures

    cross_check_table.check_constraints.append(
        CheckConstraintFeatures(
            table="projects",
            name="ck_dates",
            expression="end_date >= start_date",
            columns=["end_date", "start_date"],
        )
    )
    features = StructuralFeatures(
        dialect="sqlite",
        tables=[cross_check_table],
        schema_hash="cross",
    )

    cross_checks = analyzer._extract_cross_column_checks("projects", features)
    assert len(cross_checks) == 1
    assert cross_checks[0]["expression"] == "end_date >= start_date"
    assert cross_checks[0]["columns"]["start_date"] == "DATE"
    assert cross_checks[0]["columns"]["end_date"] == "DATE"


def test_stage3_validator_rule_14_strips_invalid_params_for_word():
    """Rule #14: GENERATOR_PARAMS validation — word does not accept min_length."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {"name": "project_name", "generator": "word", "params": {"min_length": 5, "max_length": 100}},
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # word does not accept min_length/max_length -> stripped
    assert "min_length" not in col["params"]
    assert "max_length" not in col["params"]
    assert col["generator"] == "word"


def test_stage3_validator_rule_14_keeps_valid_params_for_string():
    """Rule #14: string accepts min_length/max_length, kept."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "code", "generator": "string", "params": {"min_length": 3, "max_length": 10}},
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["params"]["min_length"] == 3
    assert col["params"]["max_length"] == 10


def test_stage3_validator_rule_15_bounds_unbounded_regex():
    """Rule #15: unbounded regex {N,} -> {N,N+5}."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "t",
                "columns": [
                    # Use a non-phone column name so Rule #23 does not upgrade
                    # the regex to NANP before Rule #15 can bound it.
                    {"name": "tracking_code", "generator": "pattern", "params": {"regex": r"\d{5,}"}},
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    regex = config["tables"][0]["columns"][0]["params"]["regex"]
    # {5,} should be replaced with {5,10}
    assert "{5,10}" in regex
    assert "{5,}" not in regex


def test_stage3_validator_rule_16_detects_fk_semantic_mismatch():
    """Rule #16: FK semantic check — created_by → users(id) should use integer generator."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    # created_by is FK to users.id (integer), but LLM chose "username" generator (string)
    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "created_by", "generator": "username", "params": {}},
                ],
            }
        ]
    }
    schema = {
        "orders": {
            "foreign_keys": [
                {"columns": ["created_by"], "ref_table": "users", "ref_columns": ["id"]},
            ]
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    # FK to integer column must use integer generator, not username (string)
    assert col["generator"] == "integer"
    assert col["params"]["max_value"] >= 1


def test_stage3_validator_rule_14_corrects_singular_choice_to_choices():
    """Rule #14: LLM typo ``choice`` (singular) -> ``choices`` (plural).

    Reproduces the P0 #2 bug observed in complex_biz.db: the LLM returned
    ``params: {choice: [...]}`` for a ``choice`` generator, and Rule #14
    stripped it (since ``choice`` is not in the accepted param set),
    leaving the generator with no choices and silently degrading to
    integer 0/1 fallback at fill time.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {
                        "name": "order_status",
                        "generator": "choice",
                        "params": {"choice": ["pending", "paid", "shipped"]},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # The singular "choice" key must be renamed to "choices", not stripped
    assert "choice" not in col["params"]
    assert "choices" in col["params"]
    assert col["params"]["choices"] == ["pending", "paid", "shipped"]
    assert col["generator"] == "choice"


def test_stage3_validator_rule_26_coerces_random_float_to_random_int_for_int_column():
    """Rule #26: random_float in derive_from expression for INTEGER column
    must be coerced to random_int.

    Reproduces the hr_biz.db bug: LLM returned ``random_float(0, value)``
    for ``actual_hours INTEGER`` column. SQLite's dynamic typing allows
    storing fractional values (e.g., 25.57) in an INTEGER column, but
    the result is semantically wrong. Rule #26 rewrites the expression
    to ``random_int(0, value)`` so the generated value is always an integer.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "tasks",
                "columns": [
                    {"name": "est_hours", "generator": "integer", "params": {"min_value": 1, "max_value": 80}},
                    {"name": "actual_hours", "derive_from": ["est_hours"], "expression": "random_float(0, value)"},
                ],
            }
        ]
    }
    schema = {
        "tasks": {
            "columns": [
                {"name": "est_hours", "type": "INTEGER"},
                {"name": "actual_hours", "type": "INTEGER"},
            ]
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][1]
    assert col["expression"] == "random_int(0, value)", (
        f"Rule #26 must coerce random_float to random_int for INTEGER column, got: {col['expression']!r}"
    )


def test_stage3_validator_rule_26_skips_real_columns():
    """Rule #26: REAL/DOUBLE/NUMERIC columns keep random_float (no coercion).

    Only INTEGER-family columns (INTEGER, INT, BIGINT, SMALLINT, TINYINT,
    MEDIUMINT) trigger the coercion. REAL columns like ``total_cost REAL``
    should retain ``random_float`` because fractional values are
    semantically correct for floating-point columns.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "base_price", "generator": "integer", "params": {"min_value": 100, "max_value": 999}},
                    {"name": "discount", "derive_from": ["base_price"], "expression": "random_float(0, value)"},
                ],
            }
        ]
    }
    schema = {
        "orders": {
            "columns": [
                {"name": "base_price", "type": "INTEGER"},
                {"name": "discount", "type": "REAL"},
            ]
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][1]
    assert col["expression"] == "random_float(0, value)", (
        f"Rule #26 must NOT coerce random_float for REAL column, got: {col['expression']!r}"
    )


def test_stage3_validator_rule_16_skips_derive_from_columns():
    """Rule #16: columns with ``derive_from`` set are skipped.

    Reproduces the P1 #3 bug: Rule #16 was re-adding ``generator+params``
    to FK columns that already had ``derive_from`` set (after Fix 1 in
    rules #1-#13 had stripped them), causing Pydantic to reject the
    config with ``cannot use both 'generator' and 'derive_from'``.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {
                        "name": "project_id",
                        "derive_from": "projects.id",
                        "expression": "value",
                    },
                ],
            }
        ]
    }
    schema = {
        "orders": {
            "foreign_keys": [
                {"columns": ["project_id"], "ref_table": "projects", "ref_columns": ["id"]},
            ]
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    # derive_from must remain; generator+params must NOT be re-added
    assert col.get("derive_from") == "projects.id"
    assert "generator" not in col
    assert "params" not in col


def test_stage3_validator_rule_16_caps_large_fk_max_value():
    """Rule #16: unreasonably large FK ``max_value`` is capped to 1000.

    Reproduces the P2 #5 bug: the LLM returned ``max_value: 1000000000``
    for an integer FK column, which produced FK values that almost
    never resolved to a parent row (parent tables typically have <1000
    rows in test datasets).
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {
                        "name": "merchant_id",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 1000000000},
                    },
                ],
            }
        ]
    }
    schema = {
        "orders": {
            "foreign_keys": [
                {"columns": ["merchant_id"], "ref_table": "merchants", "ref_columns": ["id"]},
            ]
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    # max_value must be capped at 1000; min_value unchanged
    assert col["params"]["max_value"] == 1000
    assert col["params"]["min_value"] == 1
    # generator stays as integer (already compatible)
    assert col["generator"] == "integer"


def test_stage3_validator_rule_17_rewrites_range_boolean_expression():
    """Rule #17: ``X >= 0 AND X <= value`` -> ``random_float(0, value)``.

    Reproduces the P1 #4 bug: LLMs sometimes return a boolean range
    comparison as the derive_from expression, which evaluates to
    True/False (1/0) at runtime instead of producing a meaningful
    derived value.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "discount_ratio",
                        "derive_from": "base_price",
                        "expression": "discount_ratio >= 0 AND discount_ratio <= value",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["expression"] == "random_float(0, value)"
    # derive_from preserved (the rewritten expression is a valid assignment)
    assert col.get("derive_from") == "base_price"


def test_stage3_validator_rule_17_rewrites_ge_boolean_expression():
    """Rule #17: ``X >= value`` or ``>= value`` -> ``value + random_float(0, value)``."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    for expr in ("sale_price >= value", ">= value"):
        config = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "sale_price",
                            "derive_from": "base_price",
                            "expression": expr,
                        },
                    ],
                }
            ]
        }
        validator = Stage3Validator()
        validator.validate(config)
        col = config["tables"][0]["columns"][0]
        assert col["expression"] == "value + random_float(0, value)", f"failed for expression: {expr}"
        assert col.get("derive_from") == "base_price"


def test_stage3_validator_rule_17_rewrites_le_boolean_expression():
    """Rule #17: ``X <= value`` or ``<= value`` -> ``random_float(0, value)``."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    for expr in ("sale_price <= value", "<= value"):
        config = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "sale_price",
                            "derive_from": "base_price",
                            "expression": expr,
                        },
                    ],
                }
            ]
        }
        validator = Stage3Validator()
        validator.validate(config)
        col = config["tables"][0]["columns"][0]
        assert col["expression"] == "random_float(0, value)", f"failed for expression: {expr}"
        assert col.get("derive_from") == "base_price"


def test_stage3_validator_rule_17_strips_unrecognised_boolean_expression():
    """Rule #17: unrecognised boolean expressions strip derive_from entirely.

    Falls back to the column's type-routed generator rather than producing
    True/False (1/0) values from a boolean comparison.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "is_discounted",
                        "derive_from": "base_price",
                        "expression": "value > 100 AND value < 500",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # Unrecognised boolean expression -> derive_from and expression stripped
    assert "derive_from" not in col
    assert "expression" not in col


def test_stage3_validator_rule_17_preserves_non_boolean_expression():
    """Rule #17: non-boolean expressions (e.g. ``value * 0.9``) are preserved."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "sale_price",
                        "derive_from": "base_price",
                        "expression": "value * 0.9",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # No boolean operator -> expression and derive_from preserved
    assert col["expression"] == "value * 0.9"
    assert col.get("derive_from") == "base_price"


def test_stage3_validator_rule_17_rewrites_reversed_range_boolean_expression():
    """Rule #17: ``X <= value AND X >= 0`` (reversed order) -> ``random_float(0, value)``.

    Reproduces the hr_biz tasks table failure: LLM returned
    ``actual_hours <= value AND actual_hours >= 0`` as the derive_from
    expression. The original Rule #17 range regex only matched the
    forward order ``X >= 0 AND X <= value``, so the reversed form fell
    through to the fallback branch which stripped derive_from entirely,
    leaving the column with no generator and producing all-zero values
    that violated the CHECK constraint.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "tasks",
                "columns": [
                    {
                        "name": "actual_hours",
                        "derive_from": "est_hours",
                        "expression": "actual_hours <= value AND actual_hours >= 0",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["expression"] == "random_float(0, value)", (
        "reversed-order range expression should be rewritten to random_float(0, value)"
    )
    # derive_from preserved (the rewritten expression is a valid assignment)
    assert col.get("derive_from") == "est_hours"


def test_stage3_validator_rule_17_rewrites_reversed_range_with_strict_operators():
    """Rule #17: ``X < value AND X > 0`` (strict, reversed) -> ``random_float(0, value)``."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "tasks",
                "columns": [
                    {
                        "name": "actual_hours",
                        "derive_from": "est_hours",
                        "expression": "actual_hours < value AND actual_hours > 0",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["expression"] == "random_float(0, value)"
    assert col.get("derive_from") == "est_hours"


def test_stage3_validator_rule_18_caps_unreasonable_future_end_year():
    """Rule #18: date/datetime end_year > current_year + 1 is capped.

    Reproduces the hr_biz regression: LLM returned ``end_year: 2100`` for
    ``projects.start_date``, producing dates in the 2090s (far-future).
    Test datasets should use realistic past/current dates, so cap
    end_year at ``current_year + 1`` (allows a small lookahead for
    expiry-style columns without producing 22nd-century data).
    """
    from datetime import datetime

    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "start_date",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": 2100},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    expected_cap = datetime.now().year + 1
    assert col["params"]["end_year"] == expected_cap, (
        f"end_year 2100 should be capped to current_year + 1 = {expected_cap}"
    )


def test_stage3_validator_rule_18_preserves_reasonable_end_year():
    """Rule #18: end_year <= current_year + 1 is preserved (no cap applied)."""
    from datetime import datetime

    from sqlseed_ai.staged_analyzer import Stage3Validator

    current_year = datetime.now().year
    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "start_date",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": current_year},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # Reasonable end_year should be preserved
    assert col["params"]["end_year"] == current_year


def test_stage3_validator_rule_18_caps_datetime_generator_end_year():
    """Rule #18: also caps ``datetime`` generator end_year (not just ``date``)."""
    from datetime import datetime

    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "events",
                "columns": [
                    {
                        "name": "created_at",
                        "generator": "datetime",
                        "params": {"start_year": 2020, "end_year": 2099},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    expected_cap = datetime.now().year + 1
    assert col["params"]["end_year"] == expected_cap


def test_stage3_validator_rule_19_extracts_min_value_from_check_constraint():
    """Rule #19: extract min_value from CHECK constraint ``col >= N``.

    Reproduces the hr_biz regression: LLM returned ``min_value: 0.0`` for
    ``projects.budget``, but the schema CHECK constraint requires
    ``budget >= 1000``. Rule #19 reads the CHECK expression and lifts
    the generator's min_value to satisfy the constraint.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "budget",
                        "generator": "float",
                        "params": {"min_value": 0.0, "max_value": 1000000.0, "precision": 2},
                    },
                ],
            }
        ]
    }
    schema = {
        "projects": {
            "check_constraints": [
                {"name": "chk_budget_min", "columns": ["budget"], "expression": "budget >= 1000"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    assert col["params"]["min_value"] == 1000, "min_value should be lifted to 1000 to satisfy CHECK constraint"


def test_stage3_validator_rule_19_extracts_max_value_from_check_constraint():
    """Rule #19: extract max_value from CHECK constraint ``col <= N``."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "employees",
                "columns": [
                    {
                        "name": "salary",
                        "generator": "float",
                        "params": {"min_value": 0.0, "max_value": 9999999.0, "precision": 2},
                    },
                ],
            }
        ]
    }
    schema = {
        "employees": {
            "check_constraints": [
                {"name": "chk_salary_max", "columns": ["salary"], "expression": "salary <= 200000"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    assert col["params"]["max_value"] == 200000


def test_stage3_validator_rule_19_preserves_tighter_generator_bounds():
    """Rule #19: generator's existing tighter bounds are preserved.

    If the LLM already set ``min_value: 5000`` (tighter than the CHECK
    constraint ``budget >= 1000``), the existing bound wins — Rule #19
    only lifts the floor when the generator's value would violate the
    CHECK constraint.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "budget",
                        "generator": "float",
                        "params": {"min_value": 5000.0, "max_value": 1000000.0, "precision": 2},
                    },
                ],
            }
        ]
    }
    schema = {
        "projects": {
            "check_constraints": [
                {"name": "chk_budget_min", "columns": ["budget"], "expression": "budget >= 1000"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    # Existing tighter min_value (5000) preserved — not lowered to 1000
    assert col["params"]["min_value"] == 5000.0


def test_stage3_validator_rule_19_skips_derive_from_columns():
    """Rule #19: skip columns with derive_from (no generator params to adjust)."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "sale_price",
                        "derive_from": "cost_price",
                        "expression": "value * 1.2",
                    },
                ],
            }
        ]
    }
    schema = {
        "products": {
            "check_constraints": [
                {"name": "chk_sale_price", "columns": ["sale_price"], "expression": "sale_price >= 0"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    # derive_from columns are not touched by Rule #19
    assert col.get("derive_from") == "cost_price"
    assert "params" not in col or "min_value" not in col.get("params", {})


def test_stage3_validator_rule_19_strict_inequality_gt_adds_one_for_int():
    """Rule #19: strict ``>`` inequality must add 1 for integer generators.

    Reproduces the hr_biz regression: schema has ``CHECK(est_hours > 0)``
    (strict greater-than), but the previous Rule #19 implementation
    treated ``>`` the same as ``>=``, lifting min_value to 0 — which then
    generates 0 and violates the strict CHECK. For integer generators,
    strict ``>`` must translate to ``min_value = N + 1``.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "tasks",
                "columns": [
                    {
                        "name": "est_hours",
                        "generator": "integer",
                        "params": {"min_value": 0, "max_value": 100},
                    },
                ],
            }
        ]
    }
    schema = {
        "tasks": {
            "check_constraints": [
                {"name": "chk_est_hours", "columns": ["est_hours"], "expression": "est_hours > 0"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    assert col["params"]["min_value"] == 1, (
        "strict '>' inequality must add 1 for integer generators (est_hours > 0 → min_value=1)"
    )


def test_stage3_validator_rule_19_strict_inequality_lt_subtracts_one_for_int():
    """Rule #19: strict ``<`` inequality must subtract 1 for integer generators.

    Symmetric to the ``>`` case: ``CHECK(quantity < 5)`` must translate to
    ``max_value = 4`` (not 5), otherwise 5 would be generated and violate
    the strict ``<`` CHECK.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "items",
                "columns": [
                    {
                        "name": "quantity",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 100},
                    },
                ],
            }
        ]
    }
    schema = {
        "items": {
            "check_constraints": [
                {"name": "chk_quantity", "columns": ["quantity"], "expression": "quantity < 5"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    assert col["params"]["max_value"] == 4, (
        "strict '<' inequality must subtract 1 for integer generators (quantity < 5 → max_value=4)"
    )


def test_stage3_validator_rule_19_strict_inequality_preserves_float():
    """Rule #19: strict ``>`` for float generators preserves the bound as-is.

    For floats, ``CHECK(price > 0)`` cannot be satisfied by ``min_value = 1``
    (would lose precision); instead we keep the bound and trust the random
    float generator to rarely produce exactly 0.0. This documents the
    current behavior — strict inequality on floats is a known limitation.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "price",
                        "generator": "float",
                        "params": {"min_value": 0.0, "max_value": 1000.0, "precision": 2},
                    },
                ],
            }
        ]
    }
    schema = {
        "products": {
            "check_constraints": [
                {"name": "chk_price", "columns": ["price"], "expression": "price > 0"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    # For float, strict > is preserved as the bound itself (no +1)
    assert col["params"]["min_value"] == 0.0


def test_stage3_validator_rule_17_skips_ge_value_for_date_source_column():
    """Rule #17: ``>= value`` with a DATE source column must NOT be rewritten
    to ``value + random_float(0, value)``.

    Reproduces the hr_biz regression: schema has ``CHECK(end_date >= start_date)``
    where ``start_date`` is a DATE column. The LLM translated the CHECK to a
    boolean expression ``>= value``, and the previous Rule #17 implementation
    mechanically rewrote it to ``value + random_float(0, value)`` — which
    crashes at runtime because ``float(date)`` raises TypeError (date has no
    real-number conversion). For DATE/DATETIME/TIMESTAMP source columns, the
    rewrite must be skipped (derive_from + expression stripped), letting the
    column fall back to its generator (type-routed date generator).
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "start_date",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": 2024},
                    },
                    {
                        "name": "end_date",
                        "derive_from": ["start_date"],
                        "expression": ">= value",
                    },
                ],
            }
        ]
    }
    schema = {
        "projects": {
            "columns": [
                {"name": "start_date", "type": "DATE", "nullable": False, "default": None},
                {"name": "end_date", "type": "DATE", "nullable": False, "default": None},
            ],
            "check_constraints": [
                {"name": "chk_dates", "columns": ["end_date", "start_date"], "expression": "end_date >= start_date"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    end_date_col = config["tables"][0]["columns"][1]
    # derive_from + expression must be stripped (cannot do date arithmetic
    # with random_float). The column falls back to a date generator.
    assert not end_date_col.get("derive_from"), (
        "Rule #17 must strip derive_from for DATE source columns "
        "(value + random_float(0, value) crashes on float(date))"
    )
    assert not end_date_col.get("expression"), "Rule #17 must strip expression for DATE source columns"


def test_stage3_validator_rule_17_keeps_ge_value_for_numeric_source_column():
    """Rule #17: ``>= value`` with a NUMERIC source column still rewrites
    to ``value + random_float(0, value)`` (existing behavior preserved).

    This guards against over-aggressive stripping: the type-awareness check
    must only kick in for DATE-family source columns, not for numeric ones.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "cost_price",
                        "generator": "float",
                        "params": {"min_value": 0.01, "max_value": 1000.0, "precision": 2},
                    },
                    {
                        "name": "sale_price",
                        "derive_from": ["cost_price"],
                        "expression": ">= value",
                    },
                ],
            }
        ]
    }
    schema = {
        "products": {
            "columns": [
                {"name": "cost_price", "type": "REAL", "nullable": False, "default": None},
                {"name": "sale_price", "type": "REAL", "nullable": False, "default": None},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    sale_price_col = config["tables"][0]["columns"][1]
    # For numeric source, the existing rewrite must still apply
    assert sale_price_col.get("expression") == "value + random_float(0, value)"


# ── Rule #20: sandbox-external function detection (auto-rewrite or strip) ──


def test_stage3_validator_rule_20_rewrites_floor_random_with_offset_to_random_int():
    """Rule #20: ``floor(random() * (max - min + 1)) + min`` → ``random_int(min, max)``.

    Reproduces the hr_biz regression: LLM generated
    ``floor(random() * (value - 0 + 1)) + 0`` for tasks.actual_hours, but
    ``floor`` and ``random`` are not in the simpleeval SAFE_FUNCTIONS sandbox
    (only ``random_float``/``random_int``/``random_choice`` are). The rule
    must auto-rewrite this common pattern to ``random_int(0, value)``.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "tasks",
                "columns": [
                    {
                        "name": "est_hours",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 8},
                    },
                    {
                        "name": "actual_hours",
                        "derive_from": ["est_hours"],
                        "expression": "floor(random() * (value - 0 + 1)) + 0",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    actual_col = config["tables"][0]["columns"][1]
    assert actual_col.get("expression") == "random_int(0, value)", (
        f"Rule #20 must rewrite 'floor(random() * (value - 0 + 1)) + 0' to "
        f"'random_int(0, value)', got: {actual_col.get('expression')!r}"
    )


def test_stage3_validator_rule_20_rewrites_simple_floor_random_to_random_int():
    """Rule #20: ``floor(random() * X)`` → ``random_int(0, X)``.

    Simpler pattern without offset. Reproduces LLM mistake where
    ``floor(random() * 100)`` was used (both ``floor`` and ``random``
    are sandbox-external).
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "stock",
                        "generator": "integer",
                        "params": {"min_value": 0, "max_value": 1000},
                    },
                    {
                        "name": "sold",
                        "derive_from": ["stock"],
                        "expression": "floor(random() * value)",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    sold_col = config["tables"][0]["columns"][1]
    assert sold_col.get("expression") == "random_int(0, value)", (
        f"Rule #20 must rewrite 'floor(random() * value)' to "
        f"'random_int(0, value)', got: {sold_col.get('expression')!r}"
    )


def test_stage3_validator_rule_20_rewrites_standalone_random_to_random_float():
    """Rule #20: ``random()`` (standalone, no args) → ``random_float(0, 1)``.

    LLMs sometimes write ``random()`` expecting Python's random.random()
    behaviour. The sandbox doesn't expose ``random`` (only ``random_float`` /
    ``random_int``). Rewrite to ``random_float(0, 1)`` which is the
    equivalent of ``random.random()``.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "metrics",
                "columns": [
                    {
                        "name": "score",
                        "generator": "float",
                        "params": {"min_value": 0.0, "max_value": 1.0},
                    },
                    {
                        "name": "ratio",
                        "derive_from": ["score"],
                        "expression": "random()",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    ratio_col = config["tables"][0]["columns"][1]
    assert ratio_col.get("expression") == "random_float(0, 1)", (
        f"Rule #20 must rewrite 'random()' to 'random_float(0, 1)', got: {ratio_col.get('expression')!r}"
    )


def test_stage3_validator_rule_20_strips_unknown_unrewritable_function():
    """Rule #20: unknown functions that cannot be auto-rewritten strip derive_from.

    LLM sometimes invents domain-specific helpers like ``random_markup``
    that aren't in the sandbox and have no safe rewrite. Strip derive_from +
    expression so the column falls back to its type-routed generator.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "cost_price",
                        "generator": "float",
                        "params": {"min_value": 0.01, "max_value": 1000.0, "precision": 2},
                    },
                    {
                        "name": "sale_price",
                        "derive_from": ["cost_price"],
                        "expression": "value + random_markup",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    sale_col = config["tables"][0]["columns"][1]
    # random_markup is not in SAFE_FUNCTIONS and not a recognised rewrite
    # pattern → strip derive_from + expression
    assert not sale_col.get("derive_from"), "Rule #20 must strip derive_from for unknown unrewritable functions"
    assert not sale_col.get("expression"), "Rule #20 must strip expression for unknown unrewritable functions"


def test_stage3_validator_rule_20_preserves_safe_function_expressions():
    """Rule #20: expressions using only SAFE_FUNCTIONS are preserved unchanged.

    ``value + random_float(0, value)`` uses only ``random_float`` which IS
    in the sandbox. Rule #20 must not touch it.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "cost_price",
                        "generator": "float",
                        "params": {"min_value": 0.01, "max_value": 1000.0, "precision": 2},
                    },
                    {
                        "name": "sale_price",
                        "derive_from": ["cost_price"],
                        "expression": "value + random_float(0, value)",
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    sale_col = config["tables"][0]["columns"][1]
    assert sale_col.get("expression") == "value + random_float(0, value)"


# ── Rule #22: cross-column date-CHECK range isolation ──────────────────────


def test_stage3_validator_rule_22_isolates_end_date_year_range_for_ge_check():
    """Rule #22: ``CHECK(end_date >= start_date)`` isolates date ranges.

    Both columns are date generators. Without range isolation, randomly
    generated end_date values may fall before start_date, violating the
    CHECK constraint at batch insert (sqlseed has no batch-level CHECK
    retry). The rule ensures:

      - ``end_date.start_year > start_date.end_year`` (strict isolation).
      - If end_date.start_year already exceeds start_date.end_year, no change.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "start_date",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": 2024},
                    },
                    {
                        "name": "end_date",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": 2024},
                    },
                ],
            }
        ]
    }
    schema = {
        "projects": {
            "columns": [
                {"name": "start_date", "type": "DATE", "nullable": False, "default": None},
                {"name": "end_date", "type": "DATE", "nullable": False, "default": None},
            ],
            "check_constraints": [
                {"name": "chk_dates", "columns": ["end_date", "start_date"], "expression": "end_date >= start_date"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    start_col = config["tables"][0]["columns"][0]
    end_col = config["tables"][0]["columns"][1]
    # Range isolation: end_date.start_year must be strictly > start_date.end_year
    assert end_col["params"]["start_year"] > start_col["params"]["end_year"], (
        f"Rule #22 must isolate date ranges: end_date.start_year="
        f"{end_col['params']['start_year']} must exceed "
        f"start_date.end_year={start_col['params']['end_year']}"
    )


def test_stage3_validator_rule_22_preserves_already_isolated_ranges():
    """Rule #22: skips when ranges are already isolated.

    If end_date.start_year already exceeds start_date.end_year, no adjustment
    is needed — the rule must be idempotent and not perturb valid configs.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "start_date",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": 2010},
                    },
                    {
                        "name": "end_date",
                        "generator": "date",
                        "params": {"start_year": 2015, "end_year": 2024},
                    },
                ],
            }
        ]
    }
    schema = {
        "projects": {
            "columns": [
                {"name": "start_date", "type": "DATE", "nullable": False, "default": None},
                {"name": "end_date", "type": "DATE", "nullable": False, "default": None},
            ],
            "check_constraints": [
                {"name": "chk_dates", "columns": ["end_date", "start_date"], "expression": "end_date >= start_date"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    start_col = config["tables"][0]["columns"][0]
    end_col = config["tables"][0]["columns"][1]
    # Already isolated (2015 > 2010) — no change
    assert start_col["params"]["start_year"] == 2000
    assert start_col["params"]["end_year"] == 2010
    assert end_col["params"]["start_year"] == 2015
    assert end_col["params"]["end_year"] == 2024


def test_stage3_validator_rule_22_skips_when_one_column_is_not_date_generator():
    """Rule #22: skips when one column lacks a date generator.

    If either column in the cross-column CHECK is not a date-family
    generator (e.g., integer, or derive_from), range isolation cannot
    apply — the rule must leave the columns untouched.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "events",
                "columns": [
                    {
                        "name": "start_seq",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 100},
                    },
                    {
                        "name": "end_seq",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 100},
                    },
                ],
            }
        ]
    }
    schema = {
        "events": {
            "columns": [
                {"name": "start_seq", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "end_seq", "type": "INTEGER", "nullable": False, "default": None},
            ],
            "check_constraints": [
                {"name": "chk_seq", "columns": ["end_seq", "start_seq"], "expression": "end_seq >= start_seq"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    start_col = config["tables"][0]["columns"][0]
    end_col = config["tables"][0]["columns"][1]
    # Integer columns — Rule #22 must not touch them
    assert start_col["params"]["min_value"] == 1
    assert end_col["params"]["min_value"] == 1


def test_stage3_validator_rule_22_skips_when_no_cross_column_date_check():
    """Rule #22: skips when the table has no cross-column date CHECK."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {
                        "name": "created_at",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": 2024},
                    },
                    {
                        "name": "updated_at",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": 2024},
                    },
                ],
            }
        ]
    }
    schema = {
        "users": {
            "columns": [
                {"name": "created_at", "type": "DATE", "nullable": False, "default": None},
                {"name": "updated_at", "type": "DATE", "nullable": False, "default": None},
            ],
            "check_constraints": [],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    # No CHECK → no isolation applied
    created_col = config["tables"][0]["columns"][0]
    updated_col = config["tables"][0]["columns"][1]
    assert created_col["params"]["start_year"] == 2000
    assert updated_col["params"]["start_year"] == 2000


def test_stage3_validator_rule_22_supplements_date_generator_for_stripped_column():
    """Rule #22: supplements a date generator when Rule #17 stripped it.

    Regression scenario: LLM gives ``end_date`` a ``derive_from: start_date``
    expression. Rule #17 detects start_date is DATE-family and strips the
    derive_from + expression (because ``float(date)`` would crash). This
    leaves ``end_date`` as an empty column (only ``name``).

    Rule #22 must then:
      1. Detect the CHECK(end_date >= start_date) still applies.
      2. See that end_date is a DATE column in the schema but has no generator.
      3. Supplement a date generator with a default year range.
      4. Isolate the year ranges so end_date.start_year > start_date.end_year.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "start_date",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": 2024},
                    },
                    # end_date was stripped by Rule #17 — only name remains
                    {"name": "end_date"},
                ],
            }
        ]
    }
    schema = {
        "projects": {
            "columns": [
                {"name": "start_date", "type": "DATE", "nullable": False, "default": None},
                {"name": "end_date", "type": "DATE", "nullable": False, "default": None},
            ],
            "check_constraints": [
                {"name": "chk_dates", "columns": ["end_date", "start_date"], "expression": "end_date >= start_date"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    start_col = config["tables"][0]["columns"][0]
    end_col = config["tables"][0]["columns"][1]
    # Rule #22 must supplement a date generator for the stripped end_date column
    assert end_col["generator"] == "date", (
        f"Rule #22 must supplement date generator for stripped column, got: {end_col.get('generator')}"
    )
    assert "params" in end_col
    assert "start_year" in end_col["params"]
    assert "end_year" in end_col["params"]
    # Range isolation: end_date.start_year must be strictly > start_date.end_year
    assert end_col["params"]["start_year"] > start_col["params"]["end_year"], (
        f"Rule #22 must isolate date ranges after supplementing generator: "
        f"end_date.start_year={end_col['params']['start_year']} must exceed "
        f"start_date.end_year={start_col['params']['end_year']}"
    )


def test_stage3_validator_rule_22_uses_overlap_not_union_for_midpoint():
    """Rule #22: midpoint split uses OVERLAP (intersection), not UNION.

    Regression: when start_date has start_year=2020, end_year=2025 and
    end_date has start_year=2000, end_year=2024, the union range is
    [2000, 2025] and the union midpoint is 2012. Setting
    ``start_date.end_year = 2012`` would leave start_date with an invalid
    range (start_year=2020 > end_year=2012), and the date generator would
    always return year 2020 — causing batch CHECK constraint failures.

    The fix uses the OVERLAP range [max(2000,2020), min(2024,2025)] = [2020, 2024]
    and splits at midpoint 2022:
      - start_date: {start_year: 2020, end_year: 2022}  (valid)
      - end_date:   {start_year: 2023, end_year: 2024}  (valid, isolated)

    Both individual ranges remain valid (start_year <= end_year), and
    isolation holds (2022 < 2023).
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "start_date",
                        "generator": "date",
                        "params": {"start_year": 2020, "end_year": 2025},
                    },
                    {
                        "name": "end_date",
                        "generator": "date",
                        "params": {"start_year": 2000, "end_year": 2024},
                    },
                ],
            }
        ]
    }
    schema = {
        "projects": {
            "columns": [
                {"name": "start_date", "type": "DATE", "nullable": False, "default": None},
                {"name": "end_date", "type": "DATE", "nullable": False, "default": None},
            ],
            "check_constraints": [
                {"name": "chk_dates", "columns": ["end_date", "start_date"], "expression": "end_date >= start_date"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    start_col = config["tables"][0]["columns"][0]
    end_col = config["tables"][0]["columns"][1]
    # Both individual ranges must remain valid (start_year <= end_year)
    assert start_col["params"]["start_year"] <= start_col["params"]["end_year"], (
        f"start_date range invalid: start_year={start_col['params']['start_year']} "
        f"> end_year={start_col['params']['end_year']}"
    )
    assert end_col["params"]["start_year"] <= end_col["params"]["end_year"], (
        f"end_date range invalid: start_year={end_col['params']['start_year']} "
        f"> end_year={end_col['params']['end_year']}"
    )
    # Range isolation: end_date.start_year must be strictly > start_date.end_year
    assert end_col["params"]["start_year"] > start_col["params"]["end_year"], (
        f"Rule #22 must isolate date ranges: end_date.start_year="
        f"{end_col['params']['start_year']} must exceed "
        f"start_date.end_year={start_col['params']['end_year']}"
    )


def test_stage3_validator_rule_22_resets_invalid_year_range_from_previous_buggy_run():
    """Rule #22: resets invalid year ranges left by a previous buggy run.

    Regression: an older version of Rule #22 used the UNION range midpoint,
    which could leave a column with ``start_year > end_year`` (e.g.,
    ``start_year=2020, end_year=2012``). The current Rule #22 must detect
    this invalid state on re-validation and reset to defaults (2000-2024)
    before applying range isolation.

    Without this sanity check, the rule sees ``later_start > earlier_end``
    (2013 > 2012) and skips, leaving the invalid range in place. The date
    generator then always returns ``start_year`` (2020), causing batch
    CHECK constraint failures at fill time.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    # start_date has invalid range from previous buggy run
                    {
                        "name": "start_date",
                        "generator": "date",
                        "params": {"start_year": 2020, "end_year": 2012},
                    },
                    # end_date was set by previous buggy run
                    {
                        "name": "end_date",
                        "generator": "date",
                        "params": {"start_year": 2013, "end_year": 2024},
                    },
                ],
            }
        ]
    }
    schema = {
        "projects": {
            "columns": [
                {"name": "start_date", "type": "DATE", "nullable": False, "default": None},
                {"name": "end_date", "type": "DATE", "nullable": False, "default": None},
            ],
            "check_constraints": [
                {"name": "chk_dates", "columns": ["end_date", "start_date"], "expression": "end_date >= start_date"},
            ],
        },
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    start_col = config["tables"][0]["columns"][0]
    end_col = config["tables"][0]["columns"][1]
    # Both individual ranges must be valid after re-validation
    assert start_col["params"]["start_year"] <= start_col["params"]["end_year"], (
        f"start_date range still invalid: start_year={start_col['params']['start_year']} "
        f"> end_year={start_col['params']['end_year']}"
    )
    assert end_col["params"]["start_year"] <= end_col["params"]["end_year"], (
        f"end_date range still invalid: start_year={end_col['params']['start_year']} "
        f"> end_year={end_col['params']['end_year']}"
    )
    # Range isolation: end_date.start_year must be strictly > start_date.end_year
    assert end_col["params"]["start_year"] > start_col["params"]["end_year"], (
        f"Rule #22 must isolate date ranges after reset: end_date.start_year="
        f"{end_col['params']['start_year']} must exceed "
        f"start_date.end_year={start_col['params']['end_year']}"
    )


# ---------------------------------------------------------------------------
# Rule #23: bare `phone` generator → upgraded to `pattern` with strict regex
# ---------------------------------------------------------------------------


def test_stage3_validator_rule_23_upgrades_bare_phone_to_pattern():
    """Rule #23: bare `phone` generator with no params upgrades to `pattern`.

    The Faker phone generator emits mixed formats (e.g., "+1 (555) 123-4567"
    vs "555-123-4567") that break front-end validation, and may emit invalid
    NANP area codes (e.g., "113-..." where 1xx is not a valid area code).
    Upgrading to a strict NANP pattern ensures consistent format AND realistic
    area codes / exchange numbers across all rows.

    NANP format: ``^\\+1-[2-9]\\d{2}-[2-9]\\d{2}-\\d{4}$``
      - Country code ``+1``
      - Area code ``[2-9]\\d{2}`` (cannot start with 0 or 1)
      - Exchange number ``[2-9]\\d{2}`` (cannot start with 0 or 1)
      - Subscriber number ``\\d{4}``
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "phone", "generator": "phone"},
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "pattern"
    assert "params" in col
    assert "regex" in col["params"]
    # The regex must be a realistic NANP phone pattern (area+exchange [2-9] prefix)
    assert col["params"]["regex"] == r"^\+1-[2-9]\d{2}-[2-9]\d{2}-\d{4}$"


def test_stage3_validator_rule_23_preserves_pattern_phone():
    """Rule #23: a `pattern` phone column already using realistic NANP is left untouched.

    A regex that contains ``[2-9]`` (the NANP area/exchange prefix marker) is
    considered already realistic and is preserved as-is — Rule #23 only
    upgrades simple all-digits patterns like ``^\\d{3}-\\d{3}-\\d{4}$``.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    realistic_nanp = r"^\+1-[2-9]\d{2}-[2-9]\d{2}-\d{4}$"
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {
                        "name": "phone",
                        "generator": "pattern",
                        "params": {"regex": realistic_nanp},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "pattern"
    assert col["params"]["regex"] == realistic_nanp


def test_stage3_validator_rule_23_upgrades_phone_with_empty_params():
    """Rule #23: a `phone` generator with empty params dict is still upgraded.

    The ``phone`` generator accepts no params (per ``_GENERATOR_ACCEPTED_PARAMS``),
    so any LLM-provided params are stripped by Rule #14 first, leaving an empty
    params dict. Rule #23 treats empty params as equivalent to bare (no params)
    and upgrades the column to the NANP pattern.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "phone", "generator": "phone", "params": {}},
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # Empty params dict counts as bare → still upgraded to NANP
    assert col["generator"] == "pattern"
    assert col["params"]["regex"] == r"^\+1-[2-9]\d{2}-[2-9]\d{2}-\d{4}$"


def test_stage3_validator_rule_23_skips_non_phone_columns():
    """Rule #23: columns other than `phone` are not touched."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "email", "generator": "email"},
                    {"name": "name", "generator": "name"},
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    assert config["tables"][0]["columns"][0]["generator"] == "email"
    assert config["tables"][0]["columns"][1]["generator"] == "name"


# ---------------------------------------------------------------------------
# Rule #24: UNIQUE-constrained `word`/`name` generator → upgraded to `template`
# ---------------------------------------------------------------------------


def test_stage3_validator_rule_24_upgrades_unique_word_to_template():
    """Rule #24: UNIQUE + `word` generator upgrades to `template` with sequence.

    The English lexicon has only ~hundreds of words; for 1000 UNIQUE rows the
    word generator cannot satisfy the constraint. Upgrading to a templated
    username like "word{sequence:04d}" guarantees uniqueness.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "product_name",
                        "generator": "word",
                        "constraints": {"unique": True},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "template"
    assert col["params"]["template"] == "word{sequence:04d}"
    # Preserve the UNIQUE constraint
    assert col["constraints"]["unique"] is True


def test_stage3_validator_rule_24_upgrades_unique_name_to_template():
    """Rule #24: UNIQUE + `name` (person-name) generator upgrades to template."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {
                        "name": "username",
                        "generator": "name",
                        "constraints": {"unique": True},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "template"
    assert col["params"]["template"] == "name{sequence:04d}"
    assert col["constraints"]["unique"] is True


def test_stage3_validator_rule_24_skips_non_unique_word():
    """Rule #24: a non-UNIQUE `word` column is left untouched (word is fine)."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {"name": "category_name", "generator": "word"},
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "word"


def test_stage3_validator_rule_24_skips_unique_template():
    """Rule #24: a UNIQUE `template` column (already safe) is left untouched."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {
                        "name": "code",
                        "generator": "template",
                        "params": {"template": "USER-{sequence:04d}"},
                        "constraints": {"unique": True},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "template"
    assert col["params"]["template"] == "USER-{sequence:04d}"


def test_stage3_validator_rule_24_upgrades_unique_string_code_to_template():
    """Rule #24 Case 2: UNIQUE + `string` on code-like name → `template`.

    A 10-50 char random string offers no uniqueness guarantee on 1000+ rows.
    Upgrading to ``PROJ-{sequence:04d}`` guarantees uniqueness and produces
    readable codes.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "projects",
                "columns": [
                    {
                        "name": "project_code",
                        "generator": "string",
                        "params": {"min_length": 10, "max_length": 50},
                        "constraints": {"unique": True},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "template"
    assert col["params"]["template"] == "PROJ-{sequence:04d}"
    # Old string params must be replaced (no min_length/max_length leftovers)
    assert "min_length" not in col.get("params", {})
    assert "max_length" not in col.get("params", {})


def test_stage3_validator_rule_24_detects_unique_from_schema_not_constraints():
    """Rule #24: detects UNIQUE from schema when LLM omits constraints field.

    LLMs sometimes generate ``string`` for a UNIQUE TEXT column without setting
    ``constraints.unique``. The validator should still fire by reading
    ``table_schema["unique_columns"]``.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "departments",
                "columns": [
                    {
                        "name": "dept_code",
                        "generator": "string",
                        "params": {"min_length": 5, "max_length": 10},
                        # NOTE: no constraints.unique field — LLM omitted it
                    },
                ],
            }
        ]
    }
    schema = {
        "departments": {
            "columns": [{"name": "dept_code", "type": "TEXT"}],
            "unique_columns": ["dept_code"],
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "template"
    assert col["params"]["template"] == "DEPT-{sequence:04d}"


def test_stage3_validator_rule_24_fixes_integer_on_text_code_column():
    """Rule #24 Case 3: `integer` generator on TEXT UNIQUE code column → `template`.

    LLMs sometimes generate ``integer`` for ``task_no TEXT NOT NULL UNIQUE``
    columns (a type mismatch — the column is TEXT but the LLM assumed a number).
    Upgrading to ``TASK-{sequence:04d}`` fixes both the type mismatch and
    guarantees uniqueness.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "tasks",
                "columns": [
                    {
                        "name": "task_no",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 10000},
                        "constraints": {"unique": True},
                    },
                ],
            }
        ]
    }
    schema = {
        "tasks": {
            "columns": [{"name": "task_no", "type": "TEXT"}],
            "unique_columns": ["task_no"],
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "template"
    assert col["params"]["template"] == "TASK-{sequence:04d}"
    # Old integer params must be replaced
    assert "min_value" not in col.get("params", {})


def test_stage3_validator_rule_24_skips_integer_on_non_text_code_column():
    """Rule #24 Case 3 negative: integer on INTEGER code column stays integer.

    If the column type is INTEGER (not TEXT), ``integer`` generator is correct —
    no type mismatch to fix. The column is left untouched.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "tasks",
                "columns": [
                    {
                        "name": "task_no",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 10000},
                        "constraints": {"unique": True},
                    },
                ],
            }
        ]
    }
    schema = {
        "tasks": {
            "columns": [{"name": "task_no", "type": "INTEGER"}],
            "unique_columns": ["task_no"],
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    # INTEGER column with integer generator — no fix needed
    assert col["generator"] == "integer"


def test_stage3_validator_rule_24_skips_non_code_unique_string():
    """Rule #24: a UNIQUE `string` on a non-code-like name stays as string.

    A UNIQUE ``description`` column with ``string`` generator is left alone —
    only code-like names (``_code|_no|sku|serial``) trigger the upgrade.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "description",
                        "generator": "string",
                        "params": {"min_length": 50, "max_length": 200},
                        "constraints": {"unique": True},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["generator"] == "string"
    assert col["params"]["min_length"] == 50


def test_stage3_validator_rule_24_fixes_integer_on_text_code_even_non_unique():
    """Rule #24 Case 3: integer on TEXT code column is upgraded even without UNIQUE.

    The type mismatch (integer generator on a TEXT column) is a real bug
    regardless of whether the column has a UNIQUE constraint — sqlite will
    store the integer, but the column semantically expects a code string.
    The fix upgrades to ``TASK-{sequence:04d}`` so the data is readable
    and type-correct.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "tasks",
                "columns": [
                    {
                        "name": "task_no",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 10000},
                        # NOTE: no constraints.unique, no schema unique_columns
                    },
                ],
            }
        ]
    }
    schema = {
        "tasks": {
            "columns": [{"name": "task_no", "type": "TEXT"}],
            "unique_columns": [],  # Not UNIQUE — but type mismatch still fixed
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    # Type mismatch fix fires regardless of UNIQUE
    assert col["generator"] == "template"
    assert col["params"]["template"] == "TASK-{sequence:04d}"


def test_stage3_validator_derive_code_template_prefix():
    """Helper: prefix derivation from code column names."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    assert Stage3Validator._derive_code_template_prefix("project_code") == "PROJ-"
    assert Stage3Validator._derive_code_template_prefix("task_no") == "TASK-"
    assert Stage3Validator._derive_code_template_prefix("dept_code") == "DEPT-"
    assert Stage3Validator._derive_code_template_prefix("sku") == "SKU-"
    assert Stage3Validator._derive_code_template_prefix("serial") == "SERI-"
    assert Stage3Validator._derive_code_template_prefix("category_code") == "CATE-"


def test_stage3_validator_is_text_type():
    """Helper: TEXT-family type detection."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    assert Stage3Validator._is_text_type("TEXT")
    assert Stage3Validator._is_text_type("VARCHAR(255)")
    assert Stage3Validator._is_text_type("varchar(100)")
    assert Stage3Validator._is_text_type("CHAR(10)")
    assert Stage3Validator._is_text_type("NVARCHAR(50)")
    assert Stage3Validator._is_text_type("CLOB")
    assert not Stage3Validator._is_text_type("INTEGER")
    assert not Stage3Validator._is_text_type("REAL")
    assert not Stage3Validator._is_text_type("DATE")
    assert not Stage3Validator._is_text_type("BLOB")


def test_stage3_validator_get_column_type_from_schema():
    """Helper: column type lookup from schema dict."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    schema = {
        "columns": [
            {"name": "id", "type": "INTEGER"},
            {"name": "task_no", "type": "TEXT"},
            {"name": "created_at", "type": "TIMESTAMP"},
        ]
    }
    assert Stage3Validator._get_column_type_from_schema(schema, "task_no") == "TEXT"
    assert Stage3Validator._get_column_type_from_schema(schema, "id") == "INTEGER"
    assert Stage3Validator._get_column_type_from_schema(schema, "missing") is None
    # Empty/missing columns list → None
    assert Stage3Validator._get_column_type_from_schema({}, "id") is None


def test_staged_analyzer_analyze_full_pipeline_calls_stages_in_order(monkeypatch, raw_adapter):
    """Full analyze(adapter) pipeline: stage 1 -> stage 2 -> stage 3.

    Verifies that the analyze() entry point wires up all three stages
    in the correct order, producing a config dict with table entries.
    Uses monkeypatch to mock LLM-calling internals so no real LLM is needed.
    Uses raw_adapter fixture (RawSQLiteAdapter, DatabaseAdapter Protocol-compliant).

    Anti-self-proving: tracks real call order via a shared list, and verifies
    stage 2 receives the StructureSummary produced by stage 1 (data flow
    contract), and stage 3 receives the config produced by stage 2. A wiring
    bug that skips a stage or passes the wrong artifact would fail.
    """
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer, StructureSummary, TableStructureSummary

    analyzer = StagedSchemaAnalyzer(config=None)

    # Shared list records the call order — assertions check this list rather
    # than mock.return_value echoes. This makes the test non-self-proving.
    call_log: list[str] = []
    # Captured artifacts passed between stages — verifies data flow, not
    # just call count.
    captured: dict[str, object] = {}

    # Mock stage 1 to return a StructureSummary dataclass (not dict!)
    fake_summary = StructureSummary(
        schema_hash="fake_hash",
        topological_order=["users"],
        fk_graph=[],
        tables=[
            TableStructureSummary(
                name="users",
                purpose="test",
                anchor_columns=["id"],
                naming_prefix="USER-",
                complexity=1,
                cross_column_checks=[],
                fk_references=[],
            ),
        ],
        naming_conventions={"users": "USER-"},
        complexity_score={"tables": 1, "avg_columns": 1, "avg_constraints": 0},
        dialect="sqlite",
    )

    def _fake_stage1(features):
        call_log.append("stage1")
        captured["stage1_summary"] = fake_summary
        return fake_summary

    monkeypatch.setattr(analyzer, "_run_stage1_with_fallback", _fake_stage1)

    # Mock stage 2 to return a complete config dict (Task 8 signature:
    # _run_stage2_per_column(features, summary, target_tables) -> dict[str, Any])
    def _fake_stage2(features, summary, target_tables):
        call_log.append("stage2")
        # Verify stage 2 receives the exact StructureSummary from stage 1
        # (data flow contract, not just call order).
        captured["stage2_received_summary"] = summary
        return {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {"name": "email", "generator": "email", "params": {}},
                    ],
                },
            ],
        }

    monkeypatch.setattr(analyzer, "_run_stage2_per_column", _fake_stage2)

    # Mock stage 3 to be a pass-through (rules are tested in Task 9/10)
    def _fake_stage3(config, features):
        call_log.append("stage3")
        # Verify stage 3 receives the config dict from stage 2
        captured["stage3_received_config"] = config
        return config

    monkeypatch.setattr(analyzer, "_run_stage3_validate", _fake_stage3)

    config = analyzer.analyze(raw_adapter)

    # Anti-self-proving assertion 1: stages called in correct order.
    # A bug that calls stage 3 before stage 2, or skips stage 2, would fail.
    assert call_log == ["stage1", "stage2", "stage3"], (
        f"Stages must execute in order stage1 -> stage2 -> stage3, got: {call_log}"
    )

    # Anti-self-proving assertion 2: stage 2 receives the StructureSummary
    # produced by stage 1 (data flow contract).
    assert captured["stage2_received_summary"] is fake_summary, (
        "Stage 2 must receive the StructureSummary object returned by stage 1, "
        "not a different artifact (e.g., raw features or None)."
    )

    # Anti-self-proving assertion 3: stage 3 receives the config dict
    # produced by stage 2 (data flow contract).
    stage3_config = captured["stage3_received_config"]
    assert isinstance(stage3_config, dict) and "tables" in stage3_config, (
        "Stage 3 must receive the config dict produced by stage 2."
    )
    assert stage3_config["tables"][0]["name"] == "users"

    # Pipeline produced a config dict with the expected table
    assert "tables" in config
    assert len(config["tables"]) == 1
    assert config["tables"][0]["name"] == "users"
    # stage 2 added the email column
    email_col = next(c for c in config["tables"][0]["columns"] if c["name"] == "email")
    assert email_col["generator"] == "email"


def test_decide_granularity_2b_model_uses_per_column():
    """Small model (E2B) + table with FK + UNIQUE + CHECK -> per_column."""
    from sqlseed_ai.staged_analyzer import decide_granularity

    from sqlseed.core.features import (
        CheckConstraintFeatures,
        ColumnFeatures,
        ForeignKeyFeatures,
        StructuralFeatures,
        TableFeatures,
    )

    features = StructuralFeatures(
        tables=[
            TableFeatures(
                name="orders",
                columns=[
                    ColumnFeatures(
                        name="id",
                        type="INTEGER",
                        nullable=False,
                        default=None,
                        is_primary_key=True,
                        is_autoincrement=True,
                        is_computed=False,
                    ),
                    ColumnFeatures(
                        name="user_id",
                        type="INTEGER",
                        nullable=False,
                        default=None,
                        is_primary_key=False,
                        is_autoincrement=False,
                        is_computed=False,
                    ),
                    ColumnFeatures(
                        name="amount",
                        type="REAL",
                        nullable=False,
                        default=None,
                        is_primary_key=False,
                        is_autoincrement=False,
                        is_computed=False,
                    ),
                ],
                primary_key=["id"],
                foreign_keys=[
                    ForeignKeyFeatures(
                        table="orders",
                        columns=["user_id"],
                        ref_table="users",
                        ref_columns=["id"],
                    ),
                ],
                unique_constraints=[],
                check_constraints=[
                    CheckConstraintFeatures(
                        table="orders",
                        name="ck_positive",
                        columns=["amount"],
                        expression="amount > 0",
                    ),
                ],
                indexes=[],
            ),
        ],
        dialect="sqlite",
        schema_hash="test",
    )
    # E2B model -> per_column (max LLM calls, smallest context per call)
    granularity = decide_granularity(features, model_id="gemma-4-e2b-it")
    assert granularity == "per_column"


def test_decide_granularity_7b_model_uses_per_table():
    """Mid-size model (E4B) + simple table -> per_table (balance cost and context)."""
    from sqlseed_ai.staged_analyzer import decide_granularity

    from sqlseed.core.features import (
        ColumnFeatures,
        StructuralFeatures,
        TableFeatures,
    )

    features = StructuralFeatures(
        tables=[
            TableFeatures(
                name="simple",
                columns=[
                    ColumnFeatures(
                        name="id",
                        type="INTEGER",
                        nullable=False,
                        default=None,
                        is_primary_key=True,
                        is_autoincrement=True,
                        is_computed=False,
                    ),
                    ColumnFeatures(
                        name="name",
                        type="TEXT",
                        nullable=True,
                        default=None,
                        is_primary_key=False,
                        is_autoincrement=False,
                        is_computed=False,
                    ),
                ],
                primary_key=["id"],
                foreign_keys=[],
                unique_constraints=[],
                check_constraints=[],
                indexes=[],
            ),
        ],
        dialect="sqlite",
        schema_hash="test",
    )
    # E4B model + simple table (score = 1 table = 1 < 5) -> per_table
    granularity = decide_granularity(features, model_id="gemma-4-e4b-it")
    assert granularity == "per_table"


def test_decide_granularity_cloud_model_uses_per_db():
    """Large cloud model -> per_db (single LLM call for the whole db)."""
    from sqlseed_ai.staged_analyzer import decide_granularity

    from sqlseed.core.features import (
        ColumnFeatures,
        StructuralFeatures,
        TableFeatures,
    )

    features = StructuralFeatures(
        tables=[
            TableFeatures(
                name="t1",
                columns=[
                    ColumnFeatures(
                        name="id",
                        type="INTEGER",
                        nullable=False,
                        default=None,
                        is_primary_key=True,
                        is_autoincrement=True,
                        is_computed=False,
                    ),
                ],
                primary_key=["id"],
                foreign_keys=[],
                unique_constraints=[],
                check_constraints=[],
                indexes=[],
            ),
        ],
        dialect="sqlite",
        schema_hash="test",
    )
    # 31B model + simple table (score = 1 < 20) -> per_db
    granularity = decide_granularity(features, model_id="gemma-4-31b-it")
    assert granularity == "per_db"


# ── Regression Round 2: phone/mobile realistic format, uuid→template, timestamp cross-column ──


def test_stage3_validator_rule_23_upgrades_mobile_column_name_variant():
    """Rule #23 extension: detect phone-like column names (mobile/telephone/tel/cell).

    Previously Rule #23 only triggered on ``generator == "phone"``. Now it also
    detects column-name variants (``mobile``, ``telephone``, ``tel``, ``cell``,
    ``cellphone``, ``contact_number``, ``*_phone``, ``*_mobile``) and upgrades
    bare ``phone``/``string``/``pattern`` generators on those columns to a
    realistic NANP pattern: ``^\\+1-[2-9]\\d{2}-[2-9]\\d{2}-\\d{4}$``.

    Regression: ``employees.mobile`` in hr_biz used ``pattern ^\\d{3}-\\d{3}-\\d{4}$``
    which produced random digits with invalid area codes (e.g., ``113-462-7865``
    has invalid NANP area code 113 — area codes cannot start with 0/1).
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "employees",
                "columns": [
                    {
                        "name": "mobile",
                        "generator": "pattern",
                        "params": {"regex": r"^\d{3}-\d{3}-\d{4}$"},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # Rule #23 should upgrade the simple pattern to a realistic NANP pattern
    assert col["generator"] == "pattern"
    regex = col["params"]["regex"]
    # Must enforce NANP rules: area code [2-9], exchange [2-9]
    assert "[2-9]" in regex, f"Expected NANP regex with [2-9] prefix, got: {regex}"
    assert regex.startswith("^"), f"Regex must be anchored: {regex}"


def test_stage3_validator_rule_23_handles_telephone_tel_cell_variants():
    """Rule #23 extension: all phone-like column name variants are detected."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    variants = ["telephone", "tel", "cell", "cellphone", "contact_number", "home_phone", "office_mobile"]
    validator = Stage3Validator()
    for name in variants:
        config = {
            "tables": [
                {
                    "name": "contacts",
                    "columns": [
                        {"name": name, "generator": "phone", "params": {}},
                    ],
                }
            ]
        }
        validator.validate(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "pattern", f"Column '{name}' should be upgraded to pattern"
        assert "[2-9]" in col["params"]["regex"], f"Column '{name}' should have NANP regex"


def test_stage3_validator_rule_23_skips_username_column():
    """Rule #23 extension: ``username`` (contains "name" but not phone-like) is not affected."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {
                        "name": "username",
                        "generator": "string",
                        "params": {"min_length": 5, "max_length": 20},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # username is not a phone column — Rule #23 should not touch it
    assert col["generator"] == "string"
    assert col["params"]["min_length"] == 5


def test_stage3_validator_rule_24_upgrades_uuid_on_id_column_to_template():
    """Rule #24 Case 4 (new): UNIQUE uuid on *_id column → upgrade to template.

    Regression: ``employees.employee_id`` (UNIQUE TEXT) used ``generator: uuid``
    which produces unreadable UUIDs like ``550e8400-e29b-41d4-a716-446655440000``.
    Real HR systems use readable sequential employee IDs (``EMPL-0001``).

    Case 4 triggers when:
      - Column name matches ``_id$`` (and is not literally ``uuid``/``guid``/``token``)
      - Generator is ``uuid``
      - Column has UNIQUE constraint (from col constraints OR table_schema)
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "employees",
                "columns": [
                    {
                        "name": "employee_id",
                        "generator": "uuid",
                        "params": {},
                        "constraints": {"unique": True},
                    },
                ],
            }
        ]
    }
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # Rule #24 Case 4 should upgrade uuid → template EMPL-{sequence:04d}
    assert col["generator"] == "template", f"Expected template, got {col['generator']}"
    assert col["params"]["template"] == "EMPL-{sequence:04d}", (
        f"Expected EMPL-{{sequence:04d}}, got {col['params']['template']}"
    )


def test_stage3_validator_rule_24_skips_uuid_on_uuid_named_column():
    """Rule #24 Case 4 negative: column literally named 'uuid'/'guid' stays uuid.

    Columns explicitly named ``uuid``/``guid``/``token`` are designed to hold
    random UUIDs — sequential templates would be semantically wrong.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    for col_name in ("uuid", "guid", "token", "auth_token", "session_uuid"):
        config = {
            "tables": [
                {
                    "name": "t",
                    "columns": [
                        {
                            "name": col_name,
                            "generator": "uuid",
                            "params": {},
                            "constraints": {"unique": True},
                        },
                    ],
                }
            ]
        }
        validator = Stage3Validator()
        validator.validate(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "uuid", f"Column '{col_name}' should remain uuid, got {col['generator']}"


def test_stage3_validator_rule_22_handles_timestamp_columns():
    """Rule #22 extension: TIMESTAMP columns in cross-column date CHECK are handled.

    Previously Rule #22 only processed ``date``/``datetime`` generators.
    ``timestamp`` generator was skipped (it has no ``start_year``/``end_year``
    params). Now Rule #22 converts TIMESTAMP-type columns with ``timestamp``
    generator to ``datetime`` (with default year range) before isolation, so
    ``start_time < end_time`` constraints on TIMESTAMP columns are enforced.

    Regression scenario (prevention): a future table with
    ``CHECK(end_time >= start_time)`` on TIMESTAMP columns would have been
    silently skipped, leading to batch CHECK failures.
    """
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {
        "tables": [
            {
                "name": "events",
                "columns": [
                    {
                        "name": "start_time",
                        "generator": "timestamp",
                        "params": {},
                    },
                    {
                        "name": "end_time",
                        "generator": "timestamp",
                        "params": {},
                    },
                ],
            }
        ]
    }
    schema = {
        "events": {
            "columns": [
                {"name": "start_time", "type": "TIMESTAMP"},
                {"name": "end_time", "type": "TIMESTAMP"},
            ],
            "unique_columns": [],
            "check_constraints": [
                {"expression": "end_time >= start_time", "name": "ck_times"},
            ],
        }
    }
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    start_col = config["tables"][0]["columns"][0]
    end_col = config["tables"][0]["columns"][1]
    # Both columns should be converted from timestamp → datetime with year params
    assert start_col["generator"] == "datetime", (
        f"start_time should be converted to datetime, got {start_col['generator']}"
    )
    assert end_col["generator"] == "datetime", f"end_time should be converted to datetime, got {end_col['generator']}"
    # Ranges must be isolated: end_time.start_year > start_time.end_year
    start_year_end = end_col["params"]["start_year"]
    end_year_start = start_col["params"]["end_year"]
    assert start_year_end > end_year_start, (
        f"end_time.start_year ({start_year_end}) must be > start_time.end_year ({end_year_start})"
    )
