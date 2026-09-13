"""A saved CLI run must preserve its transform when replayed."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import yaml
from click.testing import CliRunner
from sqlseed_cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_snapshot_preserves_transform_and_replays_actual_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SQLSEED_AI_ENABLED", "0")
    database = tmp_path / "snapshot.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    transform = tmp_path / "transform.py"
    transform.write_text(
        "def transform_row(row, ctx):\n    row['name'] = 'SNAPSHOT-VALUE'\n    return row\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        [
            "fill",
            str(database),
            "-t",
            "users",
            "-n",
            "3",
            "-p",
            "base",
            "--seed",
            "42",
            "--batch-size",
            "1",
            "--clear",
            "--transform",
            str(transform),
            "--snapshot",
            "--no-ai",
        ],
    )
    assert result.exit_code == 0, result.output
    expected = [(1, "SNAPSHOT-VALUE"), (2, "SNAPSHOT-VALUE"), (3, "SNAPSHOT-VALUE")]
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT id,name FROM users ORDER BY id").fetchall() == expected

    snapshots = list((tmp_path / "cache" / "snapshots").glob("*.yaml"))
    assert len(snapshots) == 1
    saved = yaml.safe_load(snapshots[0].read_text(encoding="utf-8"))
    assert saved["config"]["tables"][0]["transform"] == str(transform)
    replay = CliRunner().invoke(cli, ["replay", str(snapshots[0])])
    assert replay.exit_code == 0, replay.output
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT id,name FROM users ORDER BY id").fetchall() == expected


def test_existing_snapshot_transform_is_applied_on_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLSEED_AI_ENABLED", "0")
    database = tmp_path / "existing.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE items (value INTEGER NOT NULL)")
    transform = tmp_path / "set_value.py"
    transform.write_text("def transform_row(row, ctx):\n    row['value'] = 701\n    return row\n", encoding="utf-8")
    snapshot = tmp_path / "existing.yaml"
    snapshot.write_text(
        yaml.safe_dump(
            {
                "table_name": "items",
                "count": 2,
                "seed": 42,
                "config": {
                    "db_path": str(database),
                    "provider": "base",
                    "tables": [
                        {
                            "name": "items",
                            "count": 2,
                            "transform": str(transform),
                            "columns": [
                                {"name": "value", "generator": "integer", "params": {"min_value": 5, "max_value": 5}}
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(cli, ["replay", str(snapshot)])
    assert result.exit_code == 0, result.output
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(701,), (701,)]
