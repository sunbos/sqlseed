"""Snapshots preserve enrichment mode, not a frozen distribution of source rows."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner
from sqlseed_cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path


def _create_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, bystatus INT8 DEFAULT 1)")
        connection.executemany("INSERT INTO items(bystatus) VALUES (?)", [(7,)] * 40)
        connection.commit()


def _appended_values(path: Path, after: int) -> list[int]:
    with closing(sqlite3.connect(path)) as connection:
        return [row[0] for row in connection.execute("SELECT bystatus FROM items WHERE id > ? ORDER BY id", (after,))]


@pytest.mark.parametrize("enrich", [True, False])
def test_snapshot_preserves_enrich_and_replays_actual_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enrich: bool
) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SQLSEED_AI_ENABLED", "0")
    database = tmp_path / "items.db"
    _create_database(database)
    args = ["fill", str(database), "-t", "items", "-n", "3", "-p", "base", "--seed", "42", "--snapshot", "--no-ai"]
    if enrich:
        args.append("--enrich")
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    expected = [7 if enrich else 1] * 3
    assert _appended_values(database, 40) == expected
    snapshots = list((tmp_path / "cache" / "snapshots").glob("*.yaml"))
    assert len(snapshots) == 1
    saved = yaml.safe_load(snapshots[0].read_text(encoding="utf-8"))
    assert saved["config"]["tables"][0]["enrich"] is enrich
    replay = CliRunner().invoke(cli, ["replay", str(snapshots[0])])
    assert replay.exit_code == 0, replay.output
    assert _appended_values(database, 43) == expected


@pytest.mark.parametrize("enrich", [True, False, None])
def test_existing_snapshot_enrich_and_legacy_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enrich: bool | None
) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SQLSEED_AI_ENABLED", "0")
    database = tmp_path / "existing.db"
    _create_database(database)
    table = {"name": "items", "count": 3}
    if enrich is not None:
        table["enrich"] = enrich
    snapshot = tmp_path / "existing.yaml"
    snapshot.write_text(
        yaml.safe_dump(
            {
                "table_name": "items",
                "count": 3,
                "seed": 42,
                "config": {"db_path": str(database), "provider": "base", "tables": [table]},
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(cli, ["replay", str(snapshot)])
    assert result.exit_code == 0, result.output
    assert _appended_values(database, 40) == [7 if enrich else 1] * 3
