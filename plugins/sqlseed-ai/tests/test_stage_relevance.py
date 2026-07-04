"""Tests for stage_relevance module."""

from __future__ import annotations

from sqlseed_ai.stage_relevance import determine_stage_relevance

from sqlseed.core.features import (
    ColumnFeatures,
    ForeignKeyFeatures,
    IndexFeatures,
    StructuralFeatures,
    TableFeatures,
    UniqueConstraintFeatures,
)


def _make_features(
    *,
    has_composite_unique: bool = False,
    has_composite_fk: bool = False,
    has_collate: bool = False,
    has_strict: bool = False,
    has_partial_index: bool = False,
    has_on_conflict: bool = False,
    has_default: bool = False,
    has_autoincrement: bool = False,
    has_generated: bool = False,
) -> StructuralFeatures:
    """Build minimal StructuralFeatures for testing."""
    columns = [
        ColumnFeatures(
            name="id",
            type="INTEGER",
            nullable=False,
            default=None,
            is_primary_key=True,
            is_autoincrement=has_autoincrement,
            is_computed=False,
        ),
    ]
    if has_default:
        columns.append(
            ColumnFeatures(
                name="status",
                type="TEXT",
                nullable=False,
                default="active",
                is_primary_key=False,
                is_autoincrement=False,
                is_computed=False,
            )
        )
    if has_collate:
        columns.append(
            ColumnFeatures(
                name="name",
                type="TEXT",
                nullable=True,
                default=None,
                is_primary_key=False,
                is_autoincrement=False,
                is_computed=False,
                collation="NOCASE",
            )
        )
    if has_generated:
        columns.append(
            ColumnFeatures(
                name="total",
                type="REAL",
                nullable=False,
                default=None,
                is_primary_key=False,
                is_autoincrement=False,
                is_computed=True,
            )
        )

    unique_constraints = []
    if has_composite_unique:
        unique_constraints.append(
            UniqueConstraintFeatures(
                table="t",
                columns=["a", "b"],
                is_index_based=True,
            )
        )

    foreign_keys = []
    if has_composite_fk:
        foreign_keys.append(
            ForeignKeyFeatures(
                table="t",
                columns=["a", "b"],
                ref_table="ref",
                ref_columns=["a", "b"],
            )
        )

    indexes = []
    if has_partial_index:
        indexes.append(
            IndexFeatures(
                table="t",
                name="idx_partial",
                columns=["x"],
                is_unique=False,
                partial_predicate="x > 0",
            )
        )

    table = TableFeatures(
        name="t",
        columns=columns,
        primary_key=["id"],
        foreign_keys=foreign_keys,
        unique_constraints=unique_constraints,
        check_constraints=[],
        indexes=indexes,
        is_strict=has_strict,
        on_conflict="REPLACE" if has_on_conflict else None,
    )
    return StructuralFeatures(dialect="sqlite", tables=[table], schema_hash="test")


def test_stage_relevance_stage1_always_includes_basic_structure():
    """S1 always includes tables/columns/types/pk/fk/check/unique."""
    features = _make_features()
    rel = determine_stage_relevance(features)
    assert rel.stage1["tables"] is True
    assert rel.stage1["columns"] is True
    assert rel.stage1["types"] is True
    assert rel.stage1["pk"] is True
    assert rel.stage1["fk"] is True
    assert rel.stage1["check"] is True
    assert rel.stage1["unique"] is True


def test_stage_relevance_stage1_composite_flags():
    """S1 composite_unique/composite_fk flags set when present."""
    features = _make_features(has_composite_unique=True, has_composite_fk=True)
    rel = determine_stage_relevance(features)
    assert rel.stage1["composite_unique"] is True
    assert rel.stage1["composite_fk"] is True


def test_stage_relevance_stage2_includes_not_null_pk_fk():
    """S2 always includes not_null/pk/fk/check/unique."""
    features = _make_features()
    rel = determine_stage_relevance(features)
    assert rel.stage2["not_null"] is True
    assert rel.stage2["pk"] is True
    assert rel.stage2["fk"] is True
    assert rel.stage2["check"] is True
    assert rel.stage2["unique"] is True


def test_stage_relevance_stage2_optional_flags_off_by_default():
    """Optional S2 flags off when feature absent."""
    features = _make_features()
    rel = determine_stage_relevance(features)
    assert rel.stage2["default"] is False
    assert rel.stage2["autoincrement"] is False
    assert rel.stage2["generated"] is False
    assert rel.stage2["collate"] is False
    assert rel.stage2["strict"] is False


def test_stage_relevance_stage2_optional_flags_on_when_present():
    """Optional S2 flags on when feature present."""
    features = _make_features(
        has_default=True,
        has_autoincrement=True,
        has_generated=True,
        has_collate=True,
        has_strict=True,
        has_partial_index=True,
    )
    rel = determine_stage_relevance(features)
    assert rel.stage2["default"] is True
    assert rel.stage2["autoincrement"] is True
    assert rel.stage2["generated"] is True
    assert rel.stage2["collate"] is True
    assert rel.stage2["strict"] is True
    assert rel.stage2["partial_unique"] is True


def test_stage_relevance_stage3_includes_check_fk_unique():
    """S3 always includes check/fk/unique."""
    features = _make_features()
    rel = determine_stage_relevance(features)
    assert rel.stage3["check"] is True
    assert rel.stage3["fk"] is True
    assert rel.stage3["unique"] is True


def test_stage_relevance_stage3_postgres_always_strict():
    """S3 strict=True for PostgreSQL dialect (PG always strict)."""
    features = _make_features()
    features.dialect = "postgresql"
    rel = determine_stage_relevance(features)
    assert rel.stage3["strict"] is True


def test_stage_relevance_stage3_on_conflict_flag():
    """S3 on_conflict flag set when present (SQLite only)."""
    features = _make_features(has_on_conflict=True)
    rel = determine_stage_relevance(features)
    assert rel.stage3["on_conflict"] is True
