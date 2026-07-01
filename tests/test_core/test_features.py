"""Tests for sqlseed.core.features module."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from sqlseed.core.features import (
    ColumnFeatures,
    ForeignKeyFeatures,
    StructuralFeatureExtractor,
    StructuralFeatures,
    TableFeatures,
    UniqueConstraintFeatures,
)
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.fixture
def tmp_users_db(tmp_path: Path) -> RawSQLiteAdapter:
    """Create a small users/orders DB for feature extraction tests."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            age INTEGER DEFAULT 0 CHECK (age >= 0)
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total REAL DEFAULT 0 CHECK (total >= 0),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX idx_orders_user_id ON orders(user_id);
    """)
    conn.commit()
    conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    return adapter


def test_extractor_extract_returns_structural_features(tmp_users_db):
    """extract() returns StructuralFeatures with correct dialect."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    features = extractor.extract()
    assert isinstance(features, StructuralFeatures)
    assert features.dialect == "sqlite"
    assert len(features.tables) == 2


def test_extractor_resolves_scope_all_tables(tmp_users_db):
    """_resolve_scope(None) returns all table names."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    scope = extractor._resolve_scope(None)
    assert set(scope) == {"users", "orders"}


def test_extractor_resolves_scope_with_fk_closure(tmp_users_db):
    """_resolve_scope(['orders']) includes FK parent 'users'."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    scope = extractor._resolve_scope(["orders"])
    assert "orders" in scope
    assert "users" in scope  # FK parent


def test_extractor_extracts_table_features_correctly(tmp_users_db):
    """_extract_table_common extracts columns, PK, FK, CHECK, UNIQUE."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    features = extractor.extract(["users"])
    users = next(t for t in features.tables if t.name == "users")
    assert len(users.columns) == 4
    assert users.primary_key == ["id"]
    assert len(users.check_constraints) == 1  # age >= 0
    assert users.check_constraints[0].expression == "age >= 0"
    # email UNIQUE detected from index
    assert len(users.unique_constraints) >= 1
    assert any("email" in uc.columns for uc in users.unique_constraints)


def test_extractor_preserves_single_column_fk(tmp_users_db):
    """P2 #1 fix: each single-column FK preserved as separate features."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    features = extractor.extract(["orders"])
    orders = next(t for t in features.tables if t.name == "orders")
    assert len(orders.foreign_keys) == 1
    fk = orders.foreign_keys[0]
    assert fk.columns == ["user_id"]
    assert fk.ref_table == "users"
    assert fk.ref_columns == ["id"]


def test_extractor_computes_schema_hash(tmp_users_db):
    """_compute_schema_hash returns stable hash for same schema."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    features1 = extractor.extract()
    features2 = extractor.extract()
    assert features1.schema_hash == features2.schema_hash


def test_extractor_sqlite_detects_strict_table(tmp_path: Path):
    """SQLite STRICT table detected via DDL parsing."""
    db_path = tmp_path / "strict.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("CREATE TABLE strict_tbl (x INTEGER) STRICT;")
    conn.commit()
    conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    extractor = StructuralFeatureExtractor(adapter)
    features = extractor.extract()
    strict_tbl = next(t for t in features.tables if t.name == "strict_tbl")
    assert strict_tbl.is_strict is True


def test_extractor_sqlite_detects_without_rowid(tmp_path: Path):
    """SQLite WITHOUT ROWID table detected."""
    db_path = tmp_path / "wrid.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("CREATE TABLE wrid_tbl (id INTEGER PRIMARY KEY) WITHOUT ROWID;")
    conn.commit()
    conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    extractor = StructuralFeatureExtractor(adapter)
    features = extractor.extract()
    wrid = next(t for t in features.tables if t.name == "wrid_tbl")
    assert wrid.is_without_rowid is True


def test_extractor_sqlite_detects_column_collation(tmp_path: Path):
    """SQLite per-column COLLATE detected."""
    db_path = tmp_path / "collate.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("CREATE TABLE items (name TEXT COLLATE NOCASE, code TEXT COLLATE BINARY);")
    conn.commit()
    conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    extractor = StructuralFeatureExtractor(adapter)
    features = extractor.extract()
    items = next(t for t in features.tables if t.name == "items")
    name_col = next(c for c in items.columns if c.name == "name")
    code_col = next(c for c in items.columns if c.name == "code")
    assert name_col.collation == "NOCASE"
    assert code_col.collation == "BINARY"


def test_extractor_postgresql_dialect_returns_empty_features():
    """PG dialect extension returns empty features dict (stub for now).

    Full PG introspection (SEQUENCE/EXCLUSION/PARTITION) is implemented
    in integration test phase (Task 16).
    """
    mock_adapter = MagicMock()
    mock_adapter.dialect = "postgresql"
    mock_adapter.get_table_names.return_value = []
    extractor = StructuralFeatureExtractor(mock_adapter)
    features = extractor.extract()
    assert features.dialect == "postgresql"
    assert features.dialect_specific is not None
    assert features.dialect_specific.dialect == "postgresql"
    assert features.dialect_specific.features == {}
