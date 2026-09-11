"""Self-referencing foreign keys must use their declared target values."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from sqlseed.core.orchestrator import DataOrchestrator

if TYPE_CHECKING:
    from pathlib import Path


def test_self_reference_to_unique_non_primary_column(tmp_path: Path) -> None:
    path = tmp_path / "self_ref.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, code INTEGER NOT NULL UNIQUE, "
            "parent_code INTEGER REFERENCES nodes(code))"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "nodes",
            count=20,
            columns={"code": {"generator": "integer", "params": {"min_value": 100, "max_value": 200}}},
            seed=42,
            skip_ai=True,
        )
        assert not result.errors
        assert result.count == 20
        nodes = orch.query("SELECT id, code, parent_code FROM nodes ORDER BY id")
        assert any(node["parent_code"] is not None for node in nodes)
        for node in nodes:
            if node["parent_code"] is not None:
                assert node["parent_code"] in {previous["code"] for previous in nodes if previous["id"] < node["id"]}
        assert orch.query("PRAGMA foreign_key_check") == []


def test_self_reference_conditional_zero_root_value(tmp_path: Path) -> None:
    path = tmp_path / "zero_root.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES nodes(id), "
            "kind INTEGER NOT NULL, CHECK(kind IN (0, 1)), "
            "CHECK(kind = 0 OR parent_id IS NOT NULL), CHECK(kind != 0 OR parent_id IS NULL))"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("nodes", count=20, seed=42, skip_ai=True)
        assert not result.errors
        nodes = orch.query("SELECT parent_id, kind FROM nodes")
        assert any(node["parent_id"] is not None for node in nodes)
        assert all(node["kind"] == int(node["parent_id"] is not None) for node in nodes)


def test_self_reference_postpass_is_seeded_without_changing_global_random(tmp_path: Path) -> None:
    import random

    snapshots = []
    global_state = random.getstate()
    try:
        for index in range(2):
            path = tmp_path / f"seeded_{index}.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE nodes(id INTEGER PRIMARY KEY,parent_id INTEGER REFERENCES nodes(id))")
            with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
                result = orch.fill_table("nodes", count=30, seed=42, skip_ai=True)
                assert result.errors == [] and result.count == 30
                snapshots.append(orch.query("SELECT * FROM nodes ORDER BY id"))
                assert orch.query("PRAGMA foreign_key_check") == []
        assert snapshots[0] == snapshots[1]
        assert random.getstate() == global_state
    finally:
        random.setstate(global_state)
