"""Tests for CompositeFKCoordinator (Defense 5)."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from sqlseed_ai.validator.composite_fk import CompositeFKCoordinator
from sqlseed_ai.validator.models import ColumnGroup
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def db_with_composite_fk(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE shop_users (shop_id INTEGER, user_id INTEGER,
                PRIMARY KEY (shop_id, user_id));
            CREATE TABLE orders (id INTEGER PRIMARY KEY,
                shop_id INTEGER, user_id INTEGER,
                FOREIGN KEY (shop_id, user_id) REFERENCES shop_users(shop_id, user_id));
        """
        )
    return path


def test_identify_groups_finds_composite_fk(db_with_composite_fk: Path):
    snapshot = SchemaSnapshot(db_path=str(db_with_composite_fk))
    coord = CompositeFKCoordinator()
    groups = coord.identify_groups(snapshot)
    assert len(groups) == 1
    g = groups[0]
    assert set(g.columns) == {"shop_id", "user_id"}
    assert g.parent_table == "shop_users"
    assert g.degrade_together is True


def test_validate_group_flags_misaligned_generators():
    coord = CompositeFKCoordinator()
    g = ColumnGroup(
        group_id="g1",
        columns=["shop_id", "user_id"],
        parent_table="shop_users",
        parent_columns=["shop_id", "user_id"],
    )
    table_config = {
        "name": "orders",
        "columns": [
            {"name": "shop_id", "generator": "integer"},
            {"name": "user_id", "generator": "uuid"},
        ],
    }
    v = coord.validate_group(g, table_config)
    assert v is not None
    assert v.is_composite is True
    assert v.fix_hint == "align_group_generators"


def test_validate_group_passes_when_aligned():
    coord = CompositeFKCoordinator()
    g = ColumnGroup(
        group_id="g1",
        columns=["shop_id", "user_id"],
        parent_table="shop_users",
        parent_columns=["shop_id", "user_id"],
    )
    table_config = {
        "name": "orders",
        "columns": [
            {"name": "shop_id", "generator": "integer"},
            {"name": "user_id", "generator": "integer"},
        ],
    }
    assert coord.validate_group(g, table_config) is None


def test_coordinate_degrade_returns_all_group_cols():
    g = ColumnGroup(
        group_id="g1",
        columns=["shop_id", "user_id"],
        parent_table="shop_users",
        parent_columns=["shop_id", "user_id"],
    )
    coord = CompositeFKCoordinator()
    degraded = coord.coordinate_degrade(g, "shop_id")
    assert set(degraded) == {"shop_id", "user_id"}


def test_identify_groups_returns_empty_when_no_composite_fk(tmp_path: Path):
    """Tables with only single-column FKs produce no groups."""
    path = tmp_path / "test.db"
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE orders (id INTEGER PRIMARY KEY,
                user_id INTEGER REFERENCES users(id));
        """
        )
    snapshot = SchemaSnapshot(db_path=str(path))
    coord = CompositeFKCoordinator()
    groups = coord.identify_groups(snapshot)
    assert groups == []


def test_coordinate_degrade_returns_single_when_not_in_group():
    """When degraded_col is not in the group, only that column degrades."""
    g = ColumnGroup(
        group_id="g1",
        columns=["shop_id", "user_id"],
        parent_table="shop_users",
        parent_columns=["shop_id", "user_id"],
    )
    coord = CompositeFKCoordinator()
    degraded = coord.coordinate_degrade(g, "other_col")
    assert degraded == ["other_col"]


def test_validate_group_returns_none_when_columns_missing():
    """When table_config doesn't include all group columns, validate returns None."""
    coord = CompositeFKCoordinator()
    g = ColumnGroup(
        group_id="g1",
        columns=["shop_id", "user_id"],
        parent_table="shop_users",
        parent_columns=["shop_id", "user_id"],
    )
    table_config = {
        "name": "orders",
        "columns": [
            {"name": "shop_id", "generator": "integer"},
            # user_id missing
        ],
    }
    assert coord.validate_group(g, table_config) is None
