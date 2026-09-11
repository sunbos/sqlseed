"""Committed batches remain visible in a failed generation result."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from sqlseed.core.orchestrator import DataOrchestrator

if TYPE_CHECKING:
    from pathlib import Path


def test_second_batch_failure_reports_committed_rows(tmp_path: Path) -> None:
    path = tmp_path / "partial.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, value INTEGER NOT NULL);"
            "CREATE TRIGGER reject_later BEFORE INSERT ON items "
            "WHEN (SELECT COUNT(*) FROM items) >= 2 "
            "BEGIN SELECT RAISE(ABORT, 'second batch rejected'); END;"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=4, batch_size=2, columns={"value": "integer"}, skip_ai=True)
        assert result.errors
        assert "second batch rejected" in result.errors[0]
        assert orch.get_row_count("items") == 2
        assert result.count == 2
        assert result.batch_count == 1
