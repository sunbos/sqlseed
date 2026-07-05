"""Tests for CrossColumnValidator (2b) — cross-column constraint checks."""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from sqlseed_ai.validator.cross_column import CrossColumnValidator
from sqlseed_ai.validator.models import ConstraintType
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

if TYPE_CHECKING:
    from pathlib import Path


def _make_db(tmp_path: Path, ddl: str) -> Path:
    path = tmp_path / "t.db"
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(ddl)
    return path


def test_check_derive_from_dag_detects_2_cycle(tmp_path: Path):
    """A derives from B, B derives from A → 2-cycle violation."""
    path = _make_db(tmp_path, "CREATE TABLE t (a INTEGER, b INTEGER)")
    snapshot = SchemaSnapshot(db_path=str(path))
    validator = CrossColumnValidator()
    config = {
        "name": "t",
        "columns": [
            {"name": "a", "derive_from": ["b"], "expression": "value + 1"},
            {"name": "b", "derive_from": ["a"], "expression": "value + 2"},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []}, snapshot)
    assert any(v.constraint_type == ConstraintType.CHECK for v in violations)
    assert any(v.fix_hint == "break_derive_from_cycle" for v in violations)


def test_check_derive_from_dag_detects_self_reference(tmp_path: Path):
    """A derives from A → self-reference violation."""
    path = _make_db(tmp_path, "CREATE TABLE t (a INTEGER)")
    snapshot = SchemaSnapshot(db_path=str(path))
    validator = CrossColumnValidator()
    config = {
        "name": "t",
        "columns": [
            {"name": "a", "derive_from": "a", "expression": "value + 1"},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []}, snapshot)
    assert any(v.fix_hint == "fix_self_reference" for v in violations)


def test_check_derive_from_dag_clean_when_no_cycle(tmp_path: Path):
    """No cycle → no derive_from violations."""
    path = _make_db(tmp_path, "CREATE TABLE t (a INTEGER, b INTEGER)")
    snapshot = SchemaSnapshot(db_path=str(path))
    validator = CrossColumnValidator()
    config = {
        "name": "t",
        "columns": [
            {"name": "a", "generator": "integer"},
            {"name": "b", "derive_from": ["a"], "expression": "value + 1"},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []}, snapshot)
    assert violations == []


def test_check_fk_integrity_returns_list_without_crash(tmp_path: Path):
    """FK integrity check returns a list (may be empty)."""
    path = _make_db(
        tmp_path,
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id));
        """,
    )
    snapshot = SchemaSnapshot(db_path=str(path))
    validator = CrossColumnValidator()
    config = {
        "name": "orders",
        "columns": [
            {"name": "user_id", "generator": "integer",
             "params": {"min_value": 0, "max_value": 99999}},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []}, snapshot)
    assert isinstance(violations, list)


def test_check_fk_integrity_no_violation_when_table_not_in_snapshot(tmp_path: Path):
    """When the table is not in the snapshot, FK integrity check returns empty."""
    path = _make_db(tmp_path, "CREATE TABLE users (id INTEGER PRIMARY KEY)")
    snapshot = SchemaSnapshot(db_path=str(path))
    validator = CrossColumnValidator()
    config = {
        "name": "nonexistent_table",
        "columns": [
            {"name": "user_id", "generator": "integer",
             "params": {"max_value": 99999}},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []}, snapshot)
    assert violations == []


def test_validate_handles_string_derive_from(tmp_path: Path):
    """derive_from as a string (single dep) should work, not crash."""
    path = _make_db(tmp_path, "CREATE TABLE t (a INTEGER, b INTEGER)")
    snapshot = SchemaSnapshot(db_path=str(path))
    validator = CrossColumnValidator()
    config = {
        "name": "t",
        "columns": [
            {"name": "a", "generator": "integer"},
            {"name": "b", "derive_from": "a", "expression": "value + 1"},
        ],
    }
    violations = validator.validate(config, {"columns": [], "constraints": []}, snapshot)
    # No cycle, no self-reference → no violations
    assert violations == []
