"""Generation failures report persisted work and always restore DB settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed.config.models import ColumnConfig
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.plugins.hookspecs import hookimpl
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def _pragmas(orch: DataOrchestrator) -> list[dict[str, object]]:
    return [orch.query(f"PRAGMA {name}")[0] for name in ("synchronous", "journal_mode", "cache_size", "temp_store")]


def test_explicit_null_self_reference_preserves_check_and_old_rows(tmp_path: Path) -> None:
    path = tmp_path / "post_fill_failure.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES nodes(id), "
            "label TEXT NOT NULL, CHECK(parent_id IS NULL));"
            "INSERT INTO nodes VALUES (1, NULL, 'original root'), (2, NULL, 'original child');"
        )
    with DataOrchestrator(str(path), provider_name="base") as orch:
        before = _pragmas(orch)
        old_rows = orch.query("SELECT * FROM nodes ORDER BY id")
        result = orch.fill_table(
            "nodes",
            count=10,
            batch_size=5,
            seed=42,
            skip_ai=True,
            column_configs=[
                ColumnConfig(name="parent_id", generator="foreign_key", null_ratio=1.0),
                ColumnConfig(name="label", generator="choice", params={"choices": ["new"]}),
            ],
        )
        assert_empty(result.errors, list)
        assert_empty(orch.query("SELECT id FROM nodes WHERE parent_id IS NOT NULL"), list)
        assert result.count == 10
        assert result.batch_count == 2
        assert orch.get_row_count("nodes") == 12
        assert orch.query("SELECT * FROM nodes WHERE id <= 2 ORDER BY id") == old_rows
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)
        assert _pragmas(orch) == before


def test_derived_index_error_reports_failure_and_preserves_committed_batch(tmp_path: Path) -> None:
    path = tmp_path / "expression_failure.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, token TEXT, result TEXT)")
    with DataOrchestrator(str(path), provider_name="base") as orch:
        before = _pragmas(orch)
        result = orch.fill_table(
            "items",
            count=4,
            batch_size=2,
            seed=42,
            skip_ai=True,
            column_configs=[
                ColumnConfig(name="token", generator="template", params={"template": "{sequence}"}),
                ColumnConfig(name="result", derive_from="token", expression="value[int(value) // 3]"),
            ],
        )
        assert result.errors
        assert "index out of range" in result.errors[0]
        assert result.count == 2
        assert result.batch_count == 1
        assert orch.query("SELECT token, result FROM items ORDER BY id") == [
            {"token": "1", "result": "1"},
            {"token": "2", "result": "2"},
        ]
        assert _pragmas(orch) == before


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
def test_process_control_exceptions_propagate_and_restore_settings(
    tmp_path: Path, exception: type[BaseException]
) -> None:
    class InterruptingPlugin:
        @hookimpl
        def sqlseed_before_generate(self, table_name: str) -> None:
            raise exception("stop generation")

    path = tmp_path / "interrupted.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    with DataOrchestrator(str(path), provider_name="base") as orch:
        before = _pragmas(orch)
        orch._plugins.register(InterruptingPlugin())
        with pytest.raises(exception, match="stop generation"):
            orch.fill_table("items", count=5, skip_ai=True)
        assert orch.get_row_count("items") == 0
        assert _pragmas(orch) == before
