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
