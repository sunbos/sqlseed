"""Committed batches remain visible in a failed generation result."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlseed.core.orchestrator import DataOrchestrator
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def test_second_batch_failure_reports_committed_rows(tmp_path: Path) -> None:
    path = tmp_path / "partial.db"
    with sqlite_connection(path) as db:
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


def test_user_transform_failure_preserves_committed_batch(tmp_path: Path) -> None:
    path = tmp_path / "transform.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value INT NOT NULL)")
    transform = tmp_path / "transform.py"
    transform.write_text(
        "class RejectedRow(Exception):\n    pass\n"
        "seen = 0\n"
        "def transform_row(row, context):\n"
        "    global seen\n"
        "    seen += 1\n"
        "    if seen == 4:\n        raise RejectedRow('transform rejected fourth row')\n"
        "    return row\n",
        encoding="utf-8",
    )
    with DataOrchestrator(str(path), provider_name="base") as orch:
        result = orch.fill_table(
            "items", count=5, batch_size=2, columns={"value": "integer"}, transform=str(transform), skip_ai=True
        )
        assert result.errors == ["transform rejected fourth row"]
        assert result.count == orch.get_row_count("items") == 2
        assert result.batch_count == 1
