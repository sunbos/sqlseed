"""Real SQLite regressions for bounded batches, self references and insert counts."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed._utils.progress import NullProgressBackend
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.plugins.hookspecs import hookimpl
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

    from typing_extensions import Self


@pytest.mark.parametrize("existing", [0, 4])
def test_explicit_null_self_fk_preserves_all_rows(tmp_path: Path, existing: int) -> None:
    path = tmp_path / "self.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE nodes(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES nodes(id), label TEXT)")
        db.executemany("INSERT INTO nodes VALUES(?,NULL,'old')", [(i + 1,) for i in range(existing)])
    state = random.getstate()
    try:
        random.seed(0)
        with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
            result = orch.fill_table(
                "nodes",
                count=10,
                seed=42,
                skip_ai=True,
                columns={
                    "parent_id": {"generator": "foreign_key", "null_ratio": 1.0},
                    "label": {"generator": "choice", "params": {"choices": ["new"]}},
                },
            )
            assert_empty(result.errors, list)
            assert result.count == 10
            assert_empty(orch.query("SELECT id FROM nodes WHERE parent_id IS NOT NULL"), list)
            assert orch.query("SELECT id FROM nodes WHERE label='old' ORDER BY id") == [
                {"id": i + 1} for i in range(existing)
            ]
    finally:
        random.setstate(state)


def test_composite_fk_keeps_all_parent_pairs(tmp_path: Path) -> None:
    path = tmp_path / "pairs.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE parents(a INTEGER, b INTEGER, PRIMARY KEY(a,b));"
            "INSERT INTO parents VALUES(1,10),(1,20);"
            "CREATE TABLE children(a INTEGER NOT NULL,b INTEGER NOT NULL,PRIMARY KEY(a,b),"
            "FOREIGN KEY(a,b) REFERENCES parents(a,b));"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("children", count=2, batch_size=1, seed=42, skip_ai=True)
        assert_empty(result.errors, list)
        assert result.count == 2
        assert orch.query("SELECT * FROM children ORDER BY b") == [{"a": 1, "b": 10}, {"a": 1, "b": 20}]
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_trigger_ignored_rows_are_not_reported_as_inserted(tmp_path: Path) -> None:
    path = tmp_path / "ignored.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE items(value INTEGER NOT NULL);"
            "INSERT INTO items VALUES(9);"
            "CREATE TRIGGER ignore_one BEFORE INSERT ON items WHEN NEW.value=1 "
            "BEGIN SELECT RAISE(IGNORE); END;"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=3,
            columns={"value": {"generator": "integer", "params": {"min_value": 1, "max_value": 1}}},
            skip_ai=True,
        )
        assert_empty(result.errors, list)
        assert result.count == 0
        assert orch.query("SELECT * FROM items") == [{"value": 9}]


def test_requested_batch_size_is_a_memory_bound(tmp_path: Path) -> None:
    class Recorder:
        def __init__(self) -> None:
            self.sizes: list[int] = []

        @hookimpl
        def sqlseed_before_insert(self, batch_size: int) -> None:
            self.sizes.append(batch_size)

    path = tmp_path / "batch.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        recorder = Recorder()
        orch._plugins.register(recorder)
        result = orch.fill_table("items", count=101, batch_size=3, skip_ai=True)
        assert_empty(result.errors, list)
        assert recorder.sizes == [3] * 33 + [2]
        assert result.count == 101
        assert result.batch_count == 34
        assert orch.get_row_count("items") == 101


def test_progress_injection_leaves_lifecycle_to_caller(tmp_path: Path, capsys: Any) -> None:
    class CallerProgress(NullProgressBackend):
        entered = 0
        exited = 0
        advanced = 0

        def __enter__(self) -> Self:
            self.entered += 1
            return self

        def __exit__(self, *args: Any) -> None:
            self.exited += 1

        def update(self, task_id: Any, *, advance: int = 0, description: str | None = None) -> None:
            self.advanced += advance

    path = tmp_path / "progress.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        progress = CallerProgress()
        with progress:
            result = orch.fill_table("items", count=3, skip_ai=True, progress=progress)
            assert progress.entered == 1 and progress.exited == 0
        assert_empty(result.errors, list)
        assert result.count == 3
        assert progress.exited == 1 and progress.advanced == 3
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5])
def test_fill_rejects_bad_batch_before_clear(tmp_path: Path, batch_size: Any) -> None:
    path = tmp_path / "preflight.db"
    with sqlite_connection(path) as db:
        db.executescript("CREATE TABLE items(id INTEGER PRIMARY KEY); INSERT INTO items VALUES(41);")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        with pytest.raises(ValueError, match="batch_size"):
            orch.fill_table("items", count=1, batch_size=batch_size, clear_before=True, skip_ai=True)
        assert orch.query("SELECT id FROM items") == [{"id": 41}]


def test_old_rows_with_null_only_self_reference_targets_are_not_postprocessed(tmp_path: Path) -> None:
    path = tmp_path / "null_targets.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE nodes(id INT PRIMARY KEY, code INTEGER UNIQUE, parent_code INTEGER REFERENCES nodes(code));"
            "INSERT INTO nodes VALUES(40,NULL,NULL),(41,NULL,NULL);"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        old_rows = orch.query("SELECT * FROM nodes ORDER BY id")
        result = orch.fill_table(
            "nodes",
            count=5,
            seed=42,
            skip_ai=True,
            columns={
                "id": {"generator": "integer", "params": {"min_value": 1, "max_value": 10}},
                "code": {"generator": "integer", "params": {"min_value": 100, "max_value": 200}, "null_ratio": 0.0},
            },
        )
        assert_empty(result.errors, list)
        assert result.count == 5
        assert orch.query("SELECT * FROM nodes WHERE id IN (40,41) ORDER BY id") == old_rows
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)
