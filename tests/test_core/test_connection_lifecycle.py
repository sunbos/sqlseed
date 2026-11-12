"""Initialization failures must not leave a half-connected orchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed.config.models import ColumnAssociation
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.plugins.hookspecs import hookimpl
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

    from sqlseed.core.mapper import ColumnMapper


def test_failed_plugin_initialization_closes_connection_and_allows_retry(tmp_path: Path) -> None:
    class FailingPlugin:
        @hookimpl
        def sqlseed_register_column_mappers(self, mapper: ColumnMapper) -> None:
            raise RuntimeError("plugin initialization failed")

    orch = DataOrchestrator(str(tmp_path / "initialization.db"), provider_name="base")
    plugin = FailingPlugin()
    orch._plugins.register(plugin)
    try:
        with pytest.raises(RuntimeError, match="plugin initialization failed"), orch:
            pass
        with pytest.raises(RuntimeError, match="not connected"):
            orch.database_adapter.get_table_names()
        orch._plugins.unregister(plugin)
        with orch:
            orch.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value INTEGER)").close()
            result = orch.fill_table("items", count=3, skip_ai=True)
            assert not result.errors
            assert result.count == orch.get_row_count("items") == 3
    finally:
        orch.close()


@pytest.mark.parametrize("composite", [False, True])
def test_reopen_refreshes_foreign_key_metadata(tmp_path: Path, composite: bool) -> None:
    path = tmp_path / "migration.db"
    key = "(pa, pb)" if composite else "(pa)"
    definition = "pa INTEGER, pb INTEGER, PRIMARY KEY(pa, pb)" if composite else "pa INTEGER PRIMARY KEY"
    child_columns = "pa INTEGER NOT NULL, pb INTEGER NOT NULL" if composite else "pa INTEGER NOT NULL"
    old_key, new_key = ((1, 101), (9, 909)) if composite else ((1,), (9,))
    placeholders = "?, ?" if composite else "?"
    with sqlite_connection(path) as db:
        for name, values in (("old_parent", old_key), ("new_parent", new_key)):
            db.execute(f"CREATE TABLE {name} ({definition})")
            db.execute(f"INSERT INTO {name} VALUES ({placeholders})", values)
        db.execute(f"CREATE TABLE child ({child_columns}, FOREIGN KEY {key} REFERENCES old_parent {key})")
    orchestrator = DataOrchestrator(str(path), provider_name="base", optimize_pragma=False)
    try:
        with orchestrator:
            first = orchestrator.preview_table("child", count=2, seed=7)
            assert [tuple(row.values()) for row in first] == [old_key, old_key]
        with sqlite_connection(path) as db:
            db.execute("ALTER TABLE child RENAME TO archived_child")
            db.execute(f"CREATE TABLE child ({child_columns}, FOREIGN KEY {key} REFERENCES new_parent {key})")
        with orchestrator:
            preview = orchestrator.preview_table("child", count=2, seed=7)
            assert [tuple(row.values()) for row in preview] == [new_key, new_key]
            assert orchestrator.get_topological_table_order(["child", "new_parent"]) == ["new_parent", "child"]
            result = orchestrator.fill_table("child", count=2, batch_size=1, seed=7, skip_ai=True)
            assert result.count == 2 and result.batch_count == 2
            assert_empty(result.errors, list)
        with sqlite_connection(path) as db:
            assert db.execute("SELECT * FROM child").fetchall() == [new_key, new_key]
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        orchestrator.close()


def test_reopen_preserves_explicit_associations_and_shared_pool(tmp_path: Path) -> None:
    path = tmp_path / "associations.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO parent VALUES (42)")
        db.execute("CREATE TABLE associated (department_id INTEGER NOT NULL)")
        db.execute("CREATE TABLE pooled (shared_id INTEGER NOT NULL)")
    association = ColumnAssociation(
        column_name="department_id", source_table="parent", source_column="id", target_tables=["associated"]
    )
    orchestrator = DataOrchestrator(str(path), provider_name="base", optimize_pragma=False, associations=[association])
    try:
        with orchestrator:
            orchestrator._shared_pool.register("shared_id", [73])
            assert orchestrator.preview_table("associated", count=2, seed=4) == [{"department_id": 42}] * 2
            assert orchestrator.preview_table("pooled", count=2, seed=4) == [{"shared_id": 73}] * 2
        with orchestrator:
            assert orchestrator.preview_table("associated", count=2, seed=4) == [{"department_id": 42}] * 2
            assert orchestrator.preview_table("pooled", count=2, seed=4) == [{"shared_id": 73}] * 2
    finally:
        orchestrator.close()
