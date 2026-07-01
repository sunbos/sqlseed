"""Tests for staged_analyzer module."""

from __future__ import annotations

from sqlseed_ai.staged_analyzer import (
    ErrorCategory,
    ErrorClassifier,
    StructureSummary,
    TableStructureSummary,
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
