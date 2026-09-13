"""Tests for ShadowFKScanner (Section 14.3) — SQLite FK localization."""

from __future__ import annotations

import gc
import sqlite3
import warnings
from typing import TYPE_CHECKING

import pytest
from sqlseed_ai.validator.models import ConstraintType, ViolationReport
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot
from sqlseed_ai.validator.shadow_fk_scan import ShadowFKScanner

from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def _unlocalized_fk_report() -> ViolationReport:
    return ViolationReport(
        table="orders",
        columns=[],
        constraint_type=ConstraintType.FK,
        severity="crash",
        fix_hint="shadow_fk_scan",
    )


@pytest.fixture(name="db_with_fk")
def fixture_db_with_fk(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    with sqlite_connection(str(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                product_id INTEGER
            );
        """
        )
        conn.execute("INSERT INTO users (id) VALUES (1), (2), (3)")
        conn.execute("INSERT INTO orders (id, user_id, product_id) VALUES (1, 999, 5)")
    return path


def test_shadow_scan_identifies_offending_fk_column(db_with_fk: Path):
    snapshot = SchemaSnapshot(db_path=str(db_with_fk))
    report = _unlocalized_fk_report()
    scanner = ShadowFKScanner(str(db_with_fk), snapshot)
    updated = scanner.scan(report, batch=[{"id": 1, "user_id": 999, "product_id": 5}])
    assert updated.columns == ["user_id"]


def test_shadow_scan_noop_when_columns_already_set(db_with_fk: Path):
    snapshot = SchemaSnapshot(db_path=str(db_with_fk))
    report = ViolationReport(
        table="orders",
        columns=["user_id"],
        constraint_type=ConstraintType.FK,
        severity="crash",
    )
    scanner = ShadowFKScanner(str(db_with_fk), snapshot)
    updated = scanner.scan(report, batch=[{"user_id": 1}])
    assert updated.columns == ["user_id"]  # unchanged


def test_shadow_scan_works_with_sqlite_url(db_with_fk: Path):
    """Adversarial fix: scanner must support --url connections, not just db_path.

    Without this, Defense 3 (shadow FK localization) silently fails when
    users connect via ``--url sqlite:////path`` or in-memory SQLite.
    """
    snapshot = SchemaSnapshot(db_path=str(db_with_fk))
    report = _unlocalized_fk_report()
    # Connect via URL instead of db_path
    url = f"sqlite:///{db_with_fk}"
    scanner = ShadowFKScanner(db_path=None, snapshot=snapshot, url=url)
    updated = scanner.scan(report, batch=[{"id": 1, "user_id": 999, "product_id": 5}])
    assert updated.columns == ["user_id"]


def test_shadow_scan_returns_empty_set_when_no_connection_info(db_with_fk: Path):
    """When neither db_path nor url is provided, scanner degrades gracefully."""
    snapshot = SchemaSnapshot(db_path=str(db_with_fk))
    report = _unlocalized_fk_report()
    scanner = ShadowFKScanner(db_path=None, snapshot=snapshot, url=None)
    # Without connection info, the scanner cannot localize — returns report unchanged
    updated = scanner.scan(report, batch=[{"user_id": 999}])
    assert_empty(updated.columns, list)  # unchanged (no culprit found)


def test_shadow_scan_noop_when_constraint_type_not_fk(db_with_fk: Path):
    """Scanner should noop for non-FK violation reports."""
    snapshot = SchemaSnapshot(db_path=str(db_with_fk))
    report = ViolationReport(
        table="orders",
        columns=[],
        constraint_type=ConstraintType.UNIQUE,
        severity="crash",
    )
    scanner = ShadowFKScanner(str(db_with_fk), snapshot)
    updated = scanner.scan(report, batch=[{"id": 1}])
    assert_empty(updated.columns, list)  # unchanged


def test_shadow_scan_noop_when_snapshot_missing(db_with_fk: Path):
    """Scanner should noop when snapshot is None."""
    report = _unlocalized_fk_report()
    scanner = ShadowFKScanner(str(db_with_fk), snapshot=None)
    updated = scanner.scan(report, batch=[{"user_id": 999}])
    assert_empty(updated.columns, list)  # unchanged


def test_shadow_scan_noop_when_table_not_in_snapshot(db_with_fk: Path):
    """Scanner should noop when the report's table is not in the snapshot."""
    snapshot = SchemaSnapshot(db_path=str(db_with_fk))
    report = ViolationReport(
        table="nonexistent_table",
        columns=[],
        constraint_type=ConstraintType.FK,
        severity="crash",
        fix_hint="shadow_fk_scan",
    )
    scanner = ShadowFKScanner(str(db_with_fk), snapshot)
    updated = scanner.scan(report, batch=[{"user_id": 999}])
    assert_empty(updated.columns, list)  # unchanged


def test_shadow_scan_no_culprit_when_all_values_valid(db_with_fk: Path):
    """Scanner returns report unchanged when generated values all exist in parent."""
    snapshot = SchemaSnapshot(db_path=str(db_with_fk))
    report = _unlocalized_fk_report()
    scanner = ShadowFKScanner(str(db_with_fk), snapshot)
    # All values 1, 2 exist in parent users(id) - no culprit
    updated = scanner.scan(report, batch=[{"id": 1, "user_id": 1, "product_id": 5}])
    assert_empty(updated.columns, list)  # no culprit found


@pytest.mark.parametrize("parent_table", ["users", "missing_users"])
def test_parent_pk_load_closes_sqlite_connection(db_with_fk: Path, parent_table: str) -> None:
    """Both successful reads and query failures must release the connection."""
    scanner = ShadowFKScanner(db_path=str(db_with_fk))
    gc.collect()
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", ResourceWarning)
        if parent_table == "users":
            assert scanner._load_parent_pk_set(parent_table, "id") == {1, 2, 3}
        else:
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                scanner._load_parent_pk_set(parent_table, "id")
        gc.collect()
    assert not [str(w.message) for w in captured if issubclass(w.category, ResourceWarning)]
