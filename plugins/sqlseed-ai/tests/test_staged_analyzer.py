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
                    {"name": "phone", "generator": "pattern", "params": {"regex": r"\d{5,}"}},
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
