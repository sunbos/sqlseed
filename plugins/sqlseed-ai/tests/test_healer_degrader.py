"""Tests for healer.degrader module."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from sqlseed_ai.healer.degrader import ProgressiveDegrader
from sqlseed_ai.healer.models import DegradeReason
from sqlseed_ai.validator.models import ColumnGroup
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def snapshot(tmp_path: Path) -> SchemaSnapshot:
    path = tmp_path / "t.db"
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id));
            """
        )
    return SchemaSnapshot(db_path=str(path))


def test_degrade_preserves_successful_columns(snapshot):
    degrader = ProgressiveDegrader(snapshot)
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "email", "generator": "email"},
                ],
            }
        ]
    }
    failed = {"email": DegradeReason.LLM_FAILURE}
    new_config, _fixes = degrader.degrade(config, failed, column_groups=[])
    email_col = next(c for c in new_config["tables"][0]["columns"] if c["name"] == "email")
    assert email_col.get("_degraded") is True
    id_col = next(c for c in new_config["tables"][0]["columns"] if c["name"] == "id")
    assert id_col.get("_degraded") is not True  # preserved


def test_cascade_degrade_covers_derive_from_downstream(snapshot):
    """微调1: cascade covers derive_from (not just FK)."""
    degrader = ProgressiveDegrader(snapshot)
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "email", "generator": "email"},
                    {
                        "name": "display_email",
                        "derive_from": ["email"],
                        "expression": "value.upper()",
                    },
                ],
            }
        ]
    }
    failed = {"email": DegradeReason.LLM_FAILURE}
    new_config, _fixes = degrader.degrade(config, failed, column_groups=[])
    # display_email should be cascaded (degraded) because it derives from email
    display = next(c for c in new_config["tables"][0]["columns"] if c["name"] == "display_email")
    assert display.get("_degraded") is True


def test_cascade_degrade_handles_string_derive_from_no_substring_match(snapshot):
    """Adversarial fix: derive_from as STRING must use exact match, not substring.

    Without the fix, ``col_name in (c.get("derive_from") or [])`` would do
    substring matching when ``derive_from`` is a string. For example,
    ``"id" in "subtotal_id"`` returns True (wrong!), causing unrelated
    columns to be cascaded.
    """
    degrader = ProgressiveDegrader(snapshot)
    config = {
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "subtotal_id", "generator": "integer"},
                    # display derives from a string "subtotal_id" (not a list)
                    {
                        "name": "display",
                        "derive_from": "subtotal_id",
                        "expression": "value + 0",
                    },
                ],
            }
        ]
    }
    # Failing column is "id" — should NOT cascade to "display" because
    # display derives from "subtotal_id" (exact match), not "id".
    failed = {"id": DegradeReason.LLM_FAILURE}
    new_config, _fixes = degrader.degrade(config, failed, column_groups=[])
    display = next(c for c in new_config["tables"][0]["columns"] if c["name"] == "display")
    assert display.get("_degraded") is not True  # NOT cascaded
    # But subtotal_id-derived column WOULD cascade if subtotal_id fails:
    failed2 = {"subtotal_id": DegradeReason.LLM_FAILURE}
    new_config2, _ = degrader.degrade(config, failed2, column_groups=[])
    display2 = next(c for c in new_config2["tables"][0]["columns"] if c["name"] == "display")
    assert display2.get("_degraded") is True  # cascaded via exact string match


def test_cascade_degrade_terminates_on_cycle(snapshot):
    """Section 14.2: cycle (A derives B, B derives A) doesn't stack-overflow."""
    degrader = ProgressiveDegrader(snapshot)
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "a", "derive_from": ["b"], "expression": "value + 1"},
                    {"name": "b", "derive_from": ["a"], "expression": "value + 2"},
                ],
            }
        ]
    }
    failed = {"a": DegradeReason.LLM_FAILURE}
    # Should not raise RecursionError
    new_config, _fixes = degrader.degrade(config, failed, column_groups=[])
    # Both a and b should be degraded (cycle broken via visited set)
    a_col = next(c for c in new_config["tables"][0]["columns"] if c["name"] == "a")
    b_col = next(c for c in new_config["tables"][0]["columns"] if c["name"] == "b")
    assert a_col.get("_degraded") is True
    assert b_col.get("_degraded") is True


def test_composite_fk_group_degrades_together(snapshot):
    """Defense 5: composite FK group degrades together."""
    degrader = ProgressiveDegrader(snapshot)
    group = ColumnGroup(
        group_id="g1",
        columns=["shop_id", "user_id"],
        parent_table="shop_users",
        parent_columns=["shop_id", "user_id"],
    )
    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "shop_id", "generator": "integer"},
                    {"name": "user_id", "generator": "integer"},
                ],
            }
        ]
    }
    failed = {"shop_id": DegradeReason.LLM_FAILURE}
    new_config, _fixes = degrader.degrade(config, failed, column_groups=[group])
    # Both shop_id and user_id must be marked degraded (composite group coordination)
    shop = next(c for c in new_config["tables"][0]["columns"] if c["name"] == "shop_id")
    user = next(c for c in new_config["tables"][0]["columns"] if c["name"] == "user_id")
    assert shop.get("_degraded") is True
    assert user.get("_degraded") is True  # cascaded via group


def test_visited_set_prevents_revisit(snapshot):
    """Section 14.2: explicit visited set guarantees no double-processing."""
    degrader = ProgressiveDegrader(snapshot)
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "a", "generator": "integer"},
                ],
            }
        ]
    }
    failed = {"a": DegradeReason.LLM_OSCILLATION}
    new_config, _fixes = degrader.degrade(config, failed, column_groups=[])
    # Calling degrade twice must be idempotent for already-degraded columns
    new_config2, fixes2 = degrader.degrade(new_config, {"a": DegradeReason.LLM_OSCILLATION}, column_groups=[])
    a_col = next(c for c in new_config2["tables"][0]["columns"] if c["name"] == "a")
    assert a_col.get("_degraded") is True
    # No new fix registered on second pass for the same column
    assert all("a" not in f.columns for f in fixes2)
