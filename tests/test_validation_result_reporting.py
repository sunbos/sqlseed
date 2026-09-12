"""Standalone verification must account for fills that return errors."""

from __future__ import annotations

from scripts.complex_validation import ai_offline_validation, run_validation
from tests.sqlite_helpers import sqlite_connection


def _database_rejecting_inserts(path) -> None:
    with sqlite_connection(path) as connection:
        connection.executescript(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, value INT);"
            "CREATE TRIGGER reject_items BEFORE INSERT ON items "
            "BEGIN SELECT RAISE(ABORT, 'verification rejected insert'); END;"
        )


def test_validation_report_counts_only_committed_rows(tmp_path) -> None:
    database = tmp_path / "report.db"
    _database_rejecting_inserts(database)
    errors, elapsed, rows = run_validation.fill_db(database, {"items": 3})
    assert rows == 0
    assert elapsed >= 0
    assert "verification rejected insert" in errors["items"]


def test_offline_ai_validation_checks_result_errors(tmp_path, monkeypatch) -> None:
    database = tmp_path / "offline.db"
    _database_rejecting_inserts(database)
    monkeypatch.setattr(ai_offline_validation, "DB_DIR", tmp_path)
    ok, detail = ai_offline_validation.fill_with_config(
        {"tables": [{"name": "items", "count": 3, "columns": [{"name": "value", "generator": "integer"}]}]},
        database,
        "rejection",
    )
    assert not ok
    assert "verification rejected insert" in detail
