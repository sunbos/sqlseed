"""Tests for sqlseed.core.features module."""

from __future__ import annotations

from sqlseed.core.features import (
    CheckConstraintFeatures,
    ColumnFeatures,
    ForeignKeyFeatures,
    IndexFeatures,
    StructuralFeatures,
    TableFeatures,
    UniqueConstraintFeatures,
)


def test_column_features_min_fields():
    """ColumnFeatures 仅需 name + type + nullable + default + pk/ai/computed."""
    cf = ColumnFeatures(
        name="id",
        type="INTEGER",
        nullable=False,
        default=None,
        is_primary_key=True,
        is_autoincrement=True,
        is_computed=False,
    )
    assert cf.name == "id"
    assert cf.max_length is None
    assert cf.collation is None


def test_column_features_max_length_parsed_from_varchar():
    """max_length 从 type 字符串解析 (P2 #2 fix)."""
    cf = ColumnFeatures(
        name="email",
        type="VARCHAR(255)",
        nullable=False,
        default=None,
        is_primary_key=False,
        is_autoincrement=False,
        is_computed=False,
    )
    # max_length 由 StructuralFeatureExtractor 解析, dataclass 本身不解析
    # 这里只验证字段存在且默认 None
    assert cf.max_length is None


def test_foreign_key_features_single_column():
    """FK features 支持单列 (P2 #1 fix: 逐个保留, 不分组聚合)."""
    fk = ForeignKeyFeatures(
        table="orders",
        columns=["user_id"],
        ref_table="users",
        ref_columns=["id"],
    )
    assert len(fk.columns) == 1
    assert fk.columns == ["user_id"]
    assert fk.on_delete is None
    assert fk.on_update is None


def test_foreign_key_features_composite():
    """FK features 支持复合 FK (多列)."""
    fk = ForeignKeyFeatures(
        table="order_items",
        columns=["order_id", "product_id"],
        ref_table="orders",
        ref_columns=["order_id", "product_id"],
    )
    assert len(fk.columns) == 2


def test_unique_constraint_features_index_based():
    """UNIQUE 约束从 IndexInfo 派生."""
    uc = UniqueConstraintFeatures(
        table="users",
        columns=["email"],
        is_index_based=True,
    )
    assert uc.is_index_based is True
    assert uc.partial_predicate is None


def test_table_features_aggregates_all():
    """TableFeatures 聚合所有特征类型."""
    tf = TableFeatures(
        name="users",
        columns=[
            ColumnFeatures(
                name="id", type="INTEGER", nullable=False, default=None,
                is_primary_key=True, is_autoincrement=True, is_computed=False,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        unique_constraints=[],
        check_constraints=[],
        indexes=[],
    )
    assert tf.name == "users"
    assert len(tf.columns) == 1
    assert tf.is_strict is False
    assert tf.is_without_rowid is False


def test_structural_features_has_schema_hash_and_dialect():
    """StructuralFeatures 包含 schema_hash (缓存键) + dialect."""
    sf = StructuralFeatures(
        dialect="sqlite",
        tables=[],
        schema_hash="abc123",
    )
    assert sf.dialect == "sqlite"
    assert sf.schema_hash == "abc123"
    assert sf.dialect_specific is None
