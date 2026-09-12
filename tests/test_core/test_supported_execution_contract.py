"""Unsupported schema combinations fail before destructive fill preparation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed import fill_from_config
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._protocol import ConfigurationError
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

    from sqlseed.core.stream import DataStream


@pytest.mark.parametrize("mode", ["append", "clear", "enrich_clear", "preview"])
def test_three_column_fk_is_rejected_without_changing_existing_rows(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "unsupported.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE parents(a INTEGER,b INTEGER,c INTEGER,PRIMARY KEY(a,b,c));"
            "INSERT INTO parents VALUES(1,10,100),(2,20,200);"
            "CREATE TABLE children(a INTEGER NOT NULL,b INTEGER NOT NULL,c INTEGER NOT NULL,"
            "FOREIGN KEY(a,b,c) REFERENCES parents(a,b,c));"
            "INSERT INTO children VALUES(1,10,100);"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        with pytest.raises(ConfigurationError, match=r"children.*3-column composite foreign key.*not supported"):
            if mode == "preview":
                orch.preview_table("children", count=5, seed=42)
            else:
                orch.fill_table(
                    "children",
                    count=5,
                    batch_size=1,
                    seed=42,
                    clear_before=mode in {"clear", "enrich_clear"},
                    enrich=mode == "enrich_clear",
                    skip_ai=True,
                )
        assert orch.query("SELECT * FROM children") == [{"a": 1, "b": 10, "c": 100}]
        assert orch.query("SELECT * FROM parents ORDER BY a") == [
            {"a": 1, "b": 10, "c": 100},
            {"a": 2, "b": 20, "c": 200},
        ]
        assert orch.query("PRAGMA foreign_key_check") == []


def test_config_preflights_later_unsupported_table_before_any_write(tmp_path: Path) -> None:
    path = tmp_path / "multi.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE first(id INTEGER PRIMARY KEY,label TEXT);"
            "INSERT INTO first VALUES(7,'original');"
            "CREATE TABLE parents(a INTEGER,b INTEGER,c INTEGER,PRIMARY KEY(a,b,c));"
            "INSERT INTO parents VALUES(1,10,100);"
            "CREATE TABLE last(a INTEGER,b INTEGER,c INTEGER,FOREIGN KEY(a,b,c) REFERENCES parents(a,b,c));"
            "INSERT INTO last VALUES(1,10,100);"
        )
    config = tmp_path / "fill.json"
    config.write_text(
        json.dumps(
            {
                "db_path": str(path),
                "provider": "base",
                "tables": [{"name": "first", "count": 2}, {"name": "last", "count": 2}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match=r"last.*3-column composite foreign key.*not supported"):
        fill_from_config(str(config), clear_before=True)
    with sqlite_connection(path) as db:
        assert db.execute("SELECT * FROM first").fetchall() == [(7, "original")]
        assert db.execute("SELECT * FROM last").fetchall() == [(1, 10, 100)]


@pytest.mark.parametrize("entrypoint", ["single", "config"])
@pytest.mark.parametrize("clear_before", [False, True])
def test_missing_table_is_rejected_before_any_requested_table_changes(
    tmp_path: Path, entrypoint: str, clear_before: bool
) -> None:
    path = tmp_path / "missing.db"
    with sqlite_connection(path) as db:
        db.executescript("CREATE TABLE first(value INTEGER); INSERT INTO first VALUES(777);")
    config = tmp_path / "missing.json"
    config.write_text(
        json.dumps(
            {
                "db_path": str(path),
                "provider": "base",
                "tables": [
                    {
                        "name": "first",
                        "count": 1,
                        "columns": [{"name": "value", "generator": "choice", "params": {"choices": [8]}}],
                    },
                    {"name": "missing", "count": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    if entrypoint == "single":
        with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
            result = orch.fill_table("missing", count=1, clear_before=clear_before, skip_ai=True)
            assert result.count == 0
            assert result.batch_count == 0
            assert result.errors == ["Table 'missing' does not exist"]
    else:
        with pytest.raises(RuntimeError, match=r"Table 'missing' does not exist"):
            fill_from_config(str(config), clear_before=clear_before)
    with sqlite_connection(path) as db:
        assert db.execute("SELECT * FROM first").fetchall() == [(777,)]


def test_schema_preflight_database_error_returns_failed_result(tmp_path: Path) -> None:
    path = tmp_path / "locked.db"
    with sqlite_connection(path) as db:
        db.executescript("CREATE TABLE items(value INTEGER); INSERT INTO items VALUES(777);")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        cursor = orch.execute("PRAGMA busy_timeout=1")
        cursor.close()
        with sqlite_connection(path) as blocker:
            blocker.execute("BEGIN EXCLUSIVE")
            try:
                result = orch.fill_table("items", count=1, clear_before=True, skip_ai=True)
                assert result.count == 0
                assert result.batch_count == 0
                assert result.errors and "database is locked" in result.errors[0]
            finally:
                blocker.rollback()
        assert orch.query("SELECT * FROM items") == [{"value": 777}]


@pytest.mark.parametrize("cancel_after", [None, 0, 2])
def test_success_and_cooperative_cancel_report_actual_committed_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel_after: int | None
) -> None:
    path = tmp_path / "result.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE items(id INTEGER PRIMARY KEY,label TEXT);INSERT INTO items VALUES(7,'original');"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        build_stream = orch._build_stream

        def cancel_check() -> None:
            if cancel_after is not None and orch.get_row_count("items") - 1 >= cancel_after:
                raise ValueError("caller stopped after committed batch")

        def build_with_guard(*args: Any, **kwargs: Any) -> DataStream:
            return build_stream(*args, cancel_check=cancel_check, **kwargs)

        monkeypatch.setattr(orch, "_build_stream", build_with_guard)
        result = orch.fill_table(
            "items",
            count=5,
            batch_size=2,
            skip_ai=True,
            columns={"label": {"generator": "choice", "params": {"choices": ["new"]}}},
        )
        expected_count = 5 if cancel_after is None else cancel_after
        assert result.count == expected_count == orch.get_row_count("items") - 1
        assert result.batch_count == (3 if cancel_after is None else cancel_after // 2)
        assert result.errors == ([] if cancel_after is None else ["Generation cancelled by the caller"])
        assert orch.query("SELECT * FROM items WHERE id=7") == [{"id": 7, "label": "original"}]
