"""Replay keeps saved settings across SQLite ASCII table aliases."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import pytest
from click.testing import CliRunner
from sqlseed_cli.main import _replay_table_config, cli

from sqlseed.config.models import GeneratorConfig, TableConfig
from sqlseed.config.snapshot import SnapshotManager
from sqlseed.core.orchestrator import DataOrchestrator
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

    from sqlseed.core.result import GenerationResult


@pytest.mark.parametrize("use_url", [False, True])
@pytest.mark.parametrize(("configured", "requested"), [("Items", "Items"), ("iTeMs", "Items"), ("Items", "iTeMs")])
def test_replay_alias_preserves_columns_transform_and_batch_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_url: bool, configured: str, requested: str
) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SQLSEED_AI_ENABLED", "0")
    database = tmp_path / "example.db"
    with sqlite_connection(database) as db:
        db.executescript(
            "CREATE TABLE Items (id INTEGER PRIMARY KEY, amount INT, label TEXT);"
            "INSERT INTO Items VALUES (100,99,'original');"
        )
    transform = tmp_path / "transform.py"
    transform.write_text("def transform_row(row, ctx):\n    row['label'] = str(ctx['row_number'])\n    return row\n")
    target = {"url": f"sqlite:///{database}"} if use_url else {"db_path": str(database)}
    config = GeneratorConfig.model_validate(
        {
            **target,
            "provider": "base",
            "optimize_pragma": False,
            "tables": [
                {
                    "name": configured,
                    "count": 3,
                    "batch_size": 2,
                    "transform": str(transform),
                    "columns": [{"name": "amount", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
                }
            ],
        }
    )
    frozen = copy.deepcopy(config.model_dump())
    snapshot = SnapshotManager(str(tmp_path / "snapshots")).save(config, requested, 3, 42)
    results: list[GenerationResult] = []
    original_fill = DataOrchestrator.fill_table

    def record_fill(self: DataOrchestrator, *args: Any, **kwargs: Any) -> GenerationResult:
        result = original_fill(self, *args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(DataOrchestrator, "fill_table", record_fill)
    result = CliRunner().invoke(cli, ["replay", snapshot])
    assert result.exit_code == 0, result.output
    assert len(results) == 1 and results[0].batch_count == 2
    with sqlite_connection(database) as db:
        assert db.execute("SELECT amount,label FROM Items ORDER BY id").fetchall() == [
            (99, "original"),
            (7, "1"),
            (7, "2"),
            (7, "3"),
        ]
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert config.model_dump() == frozen


def test_replay_non_ascii_names_stay_distinct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    database = tmp_path / "unicode.db"
    with sqlite_connection(database) as db:
        db.executescript('CREATE TABLE "Ä" (amount INT); CREATE TABLE "ä" (amount INT);')
    config = GeneratorConfig.model_validate(
        {
            "db_path": str(database),
            "provider": "base",
            "optimize_pragma": False,
            "tables": [
                {
                    "name": name,
                    "columns": [
                        {"name": "amount", "generator": "integer", "params": {"min_value": value, "max_value": value}}
                    ],
                }
                for name, value in (("Ä", 7), ("ä", 9))
            ],
        }
    )
    snapshot = SnapshotManager(str(tmp_path / "snapshots")).save(config, "ä", 2, 42)
    result = CliRunner().invoke(cli, ["replay", snapshot])
    assert result.exit_code == 0, result.output
    with sqlite_connection(database) as db:
        assert db.execute('SELECT amount FROM "Ä"').fetchall() == []
        assert db.execute('SELECT amount FROM "ä"').fetchall() == [(9,), (9,)]


def test_replay_ambiguous_aliases_rejected_before_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    database = tmp_path / "ambiguous.db"
    with sqlite_connection(database) as db:
        db.executescript("CREATE TABLE Items (amount INT); INSERT INTO Items VALUES (99);")
    config = GeneratorConfig(
        db_path=str(database),
        provider="base",
        optimize_pragma=False,
        tables=[TableConfig(name="Items"), TableConfig(name="iTeMs")],
    )
    snapshot = SnapshotManager(str(tmp_path / "snapshots")).save(config, "Items", 2, 42)
    before = database.read_bytes()
    result = CliRunner().invoke(cli, ["replay", snapshot])
    assert result.exit_code == 2, result.output
    assert "multiple configurations for the replay table" in result.output
    assert database.read_bytes() == before
    with sqlite_connection(database) as db:
        assert db.execute("SELECT amount FROM Items").fetchall() == [(99,)]


def test_replay_without_table_config_preserves_legacy_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    database = tmp_path / "legacy.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE Items (id INTEGER PRIMARY KEY, amount REAL)")
    config = GeneratorConfig(db_path=str(database), provider="base", optimize_pragma=False)
    with DataOrchestrator.from_config(config) as orchestrator:
        direct = orchestrator.fill_table("Items", count=2, seed=42)
    assert direct.count == 2
    assert_empty(direct.errors, list)
    with sqlite_connection(database) as db:
        expected = db.execute("SELECT amount FROM Items ORDER BY id").fetchall()
    snapshot = SnapshotManager(str(tmp_path / "snapshots")).save(config, "Items", 2, 42)
    result = CliRunner().invoke(cli, ["replay", snapshot])
    assert result.exit_code == 0, result.output
    with sqlite_connection(database) as db:
        assert db.execute("SELECT amount FROM Items ORDER BY id").fetchall() == expected + expected


def test_replay_postgresql_name_matching_is_exact() -> None:
    config = GeneratorConfig(url="postgresql://localhost/example", tables=[TableConfig(name="Items")])
    assert _replay_table_config(config, "Items", "postgresql") is config.tables[0]
    assert _replay_table_config(config, "items", "postgresql") is None
