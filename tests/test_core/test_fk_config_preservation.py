"""Explicit FK hydration must not put database values into caller configs."""

from __future__ import annotations

from pathlib import Path

import pytest

from sqlseed import connect
from sqlseed.config.models import ColumnConfig, GeneratorConfig, TableConfig
from sqlseed.config.snapshot import SnapshotManager
from tests.sqlite_helpers import sqlite_connection


@pytest.mark.parametrize("operation", ["preview", "fill"])
def test_explicit_fk_preserves_caller_config_and_snapshot(tmp_path: Path, operation: str) -> None:
    database = tmp_path / "foreign-key.sqlite"
    with sqlite_connection(database) as db:
        db.executescript(
            "CREATE TABLE parent(code TEXT PRIMARY KEY);"
            "INSERT INTO parent VALUES ('alpha'), ('beta');"
            "CREATE TABLE child(id INTEGER PRIMARY KEY, parent_code TEXT NOT NULL REFERENCES parent(code));"
            "INSERT INTO child VALUES (1, 'alpha');"
        )
    column = ColumnConfig(
        name="parent_code",
        generator="foreign_key",
        params={"ref_table": "parent", "ref_column": "code", "strategy": "coverage"},
    )
    config = GeneratorConfig(
        db_path=str(database),
        provider="base",
        optimize_pragma=False,
        tables=[TableConfig(name="child", count=6, columns=[column])],
    )
    expected_model = config.model_dump(mode="json")
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    initial_snapshot = Path(manager.save(config, "child", 6, seed=0))
    initial_bytes = initial_snapshot.read_bytes()
    with connect(db_path=str(database), provider="base", optimize_pragma=False) as orch:
        for stage in (1, 2):
            expected_codes = {"alpha", "beta"} if stage == 1 else {"alpha", "beta", "gamma"}
            if stage == 2:
                with sqlite_connection(database) as db:
                    db.execute("INSERT INTO parent VALUES ('gamma')")
            before = database.read_bytes()
            if operation == "preview":
                rows = orch.preview_table("child", count=6, seed=0, column_configs=[column])
                assert {row["parent_code"] for row in rows} == expected_codes
                assert database.read_bytes() == before
            else:
                result = orch.fill_table("child", count=6, batch_size=4, seed=0, column_configs=[column], skip_ai=True)
                assert result.count == 6 and result.batch_count == 2 and result.errors == []
            with sqlite_connection(database) as db:
                rows = db.execute("SELECT id, parent_code FROM child ORDER BY id").fetchall()
                assert rows[0] == (1, "alpha")
                if operation == "fill":
                    assert len(rows) == 1 + stage * 6
                    assert {row[1] for row in rows[-6:]} == expected_codes
                else:
                    assert rows == [(1, "alpha")]
                assert db.execute("PRAGMA foreign_key_check").fetchall() == []
                assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            saved = manager.save(config, "child", 6, seed=0)
            assert manager.load(saved)["config"] == expected_model
            assert config.model_dump(mode="json") == expected_model
            assert initial_snapshot.read_bytes() == initial_bytes
