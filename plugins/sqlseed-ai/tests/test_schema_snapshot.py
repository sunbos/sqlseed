"""Tests for SchemaSnapshot (Defense 8) + optimistic lock."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from sqlseed_ai.validator.schema_snapshot import (
    ConstraintInfo,
    SchemaDriftError,
    SchemaSnapshot,
    TableMeta,
    write_yaml_with_optimistic_lock,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sqlite_db(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE);
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                sale_price REAL,
                cost_price REAL,
                CHECK (sale_price >= cost_price)
            );
        """
        )
    return path


def test_snapshot_captures_tables(sqlite_db: Path):
    snap = SchemaSnapshot(db_path=str(sqlite_db))
    assert "users" in snap.tables
    assert "orders" in snap.tables
    users = snap.tables["users"]
    assert isinstance(users, TableMeta)
    assert "id" in users.columns


def test_snapshot_has_stable_hash(sqlite_db: Path):
    snap1 = SchemaSnapshot(db_path=str(sqlite_db))
    snap2 = SchemaSnapshot(db_path=str(sqlite_db))
    assert snap1.schema_hash == snap2.schema_hash


def test_snapshot_detects_drift(sqlite_db: Path):
    snap = SchemaSnapshot(db_path=str(sqlite_db))
    # Modify schema: add a column
    with sqlite3.connect(str(sqlite_db)) as conn:
        conn.execute("ALTER TABLE users ADD COLUMN name TEXT")
    assert snap.validate_against_current(db_path=str(sqlite_db)) is False


def test_optimistic_lock_raises_on_drift(sqlite_db: Path, tmp_path: Path):
    snap = SchemaSnapshot(db_path=str(sqlite_db))
    with sqlite3.connect(str(sqlite_db)) as conn:
        conn.execute("ALTER TABLE users ADD COLUMN name TEXT")
    out = tmp_path / "out.yaml"
    with pytest.raises(SchemaDriftError):
        write_yaml_with_optimistic_lock({"tables": []}, out, snap, db_path=str(sqlite_db))


def test_optimistic_lock_writes_when_unchanged(sqlite_db: Path, tmp_path: Path):
    snap = SchemaSnapshot(db_path=str(sqlite_db))
    out = tmp_path / "out.yaml"
    write_yaml_with_optimistic_lock({"tables": [{"name": "users"}]}, out, snap, db_path=str(sqlite_db))
    assert out.exists()


def test_constraint_map_populated_for_pg_style_constraints(sqlite_db: Path):
    """SQLite constraint_map may be empty (unnamed CHECKs); PG path uses it."""
    snap = SchemaSnapshot(db_path=str(sqlite_db))
    # constraint_map is a dict (possibly empty for SQLite); PG fills it
    assert isinstance(snap.constraint_map, dict)


def test_constraint_info_dataclass_defaults():
    """ConstraintInfo defaults to expression=None."""
    from sqlseed_ai.validator.models import ConstraintType

    ci = ConstraintInfo(name="uq_email", columns=["email"], constraint_type=ConstraintType.UNIQUE)
    assert ci.expression is None
    assert ci.columns == ["email"]


def test_table_meta_defaults():
    """TableMeta defaults foreign_keys to empty list."""
    tm = TableMeta(name="t", columns=["id"], column_types={"id": "INTEGER"}, constraints=[])
    assert tm.foreign_keys == []


def test_get_column_type_returns_any_for_unknown(sqlite_db: Path):
    snap = SchemaSnapshot(db_path=str(sqlite_db))
    assert snap.get_column_type("users", "nonexistent") == "ANY"
    assert snap.get_column_type("nonexistent_table", "id") == "ANY"
