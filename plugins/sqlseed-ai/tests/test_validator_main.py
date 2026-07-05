"""Tests for FastValidator orchestrator (Section 4.7, 14.3)."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
from sqlseed_ai.contracts.matrix import ContractResolver
from sqlseed_ai.validator.main import FastValidator
from sqlseed_ai.validator.models import ConstraintType
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def snapshot(tmp_path: Path) -> SchemaSnapshot:
    path = tmp_path / "t.db"
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE);
            CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id));
        """
        )
    return SchemaSnapshot(db_path=str(path))


def test_validate_clean_config_returns_no_violations(snapshot: SchemaSnapshot):
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = FastValidator(resolver, db_path=snapshot.db_path)
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer", "params": {"min_value": 1, "max_value": 9999}},
                    {"name": "email", "generator": "email"},
                ],
            },
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "generator": "integer", "params": {"min_value": 1, "max_value": 9999}},
                    {"name": "user_id", "generator": "integer", "params": {"min_value": 1, "max_value": 9999}},
                ],
            },
        ]
    }
    result = validator.validate(config, snapshot)
    assert result.is_clean


def test_validate_reports_crash_violation(snapshot: SchemaSnapshot):
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = FastValidator(resolver, db_path=snapshot.db_path)
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "email", "generator": "integer"},  # CRASH: integer on TEXT
                ],
            },
        ]
    }
    result = validator.validate(config, snapshot)
    assert not result.is_clean
    assert any(v.table == "users" for v in result.violations)


def test_validate_runs_shadow_scan_for_fk_error(snapshot: SchemaSnapshot):
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    validator = FastValidator(resolver, db_path=snapshot.db_path)
    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "user_id", "generator": "integer"},
                ],
            }
        ]
    }
    # Simulate FK violation from DB
    fk_err = sqlite3.IntegrityError("FOREIGN KEY constraint failed")
    result = validator.validate(
        config,
        snapshot,
        fill_error=fk_err,
        dialect="sqlite",
        batch=[{"user_id": 999}],
    )
    fk_violations = [v for v in result.violations if v.constraint_type == ConstraintType.FK]
    assert len(fk_violations) == 1
    # Shadow scan should have localized the column
    assert fk_violations[0].columns == ["user_id"]
