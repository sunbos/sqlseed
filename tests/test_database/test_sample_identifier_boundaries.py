"""Sample queries preserve quoted identifiers and raw DBAPI value contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.config.models import ColumnConfig
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def test_row_count_does_not_require_foreign_key_target_reflection(tmp_path: Path) -> None:
    database = tmp_path / "missing-parent.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE child(value INTEGER, parent_id INTEGER REFERENCES missing_parent(id))")
        db.execute("INSERT INTO child VALUES (17, 1)")
        assert db.execute("SELECT COUNT(*) FROM child").fetchone() == (1,)
    before = database.read_bytes()
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(database))
        assert adapter.get_row_count("child") == 1
    assert database.read_bytes() == before


@pytest.mark.parametrize("operation", ["sample", "column_values", "row_count"])
def test_quoted_colons_are_identifiers_not_bind_parameters(tmp_path: Path, operation: str) -> None:
    database = tmp_path / "quoted.db"
    document = '{ "status": "ready", "items": [1, 2] }'
    with sqlite_connection(database) as db:
        db.execute('CREATE TABLE ":events"(":value" INTEGER, "payload:json" JSON, "day:date" DATE)')
        db.executemany('INSERT INTO ":events" VALUES (?, ?, ?)', [(7, document, "2026-09-29")] * 2)
        db.execute("CREATE TABLE events(value INTEGER)")
        db.execute("INSERT INTO events VALUES (99)")
    before = database.read_bytes()
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(database))
        if operation == "sample":
            assert adapter.get_sample_rows(":events", limit=1) == [
                {":value": 7, "payload:json": document, "day:date": "2026-09-29"}
            ]
            assert adapter.get_sample_rows(":events", limit=1, columns=[":value"]) == [{":value": 7}]
        elif operation == "column_values":
            assert adapter.get_column_values(":events", ":value", limit=1) == [7]
            assert adapter.get_column_values(":events", "payload:json", limit=1) == [document]
            assert adapter.get_column_values(":events", "day:date", limit=1) == ["2026-09-29"]
        else:
            assert adapter.get_row_count(":events") == 2
            assert adapter.get_row_count("events") == 1
    assert database.read_bytes() == before


def test_colon_table_schema_and_preview_leave_the_existing_data_unchanged(tmp_path: Path) -> None:
    database = tmp_path / "preview.db"
    with sqlite_connection(database) as db:
        db.execute('CREATE TABLE ":events"(":value" INTEGER NOT NULL)')
        db.execute('INSERT INTO ":events" VALUES (17)')
        db.execute("CREATE TABLE events(value INTEGER)")
        db.execute("INSERT INTO events VALUES (99)")
    before = database.read_bytes()
    with DataOrchestrator(str(database), provider_name="base", optimize_pragma=False) as orch:
        context = orch.get_schema_context(":events")
        assert context["sample_data"] == [{":value": 17}]
        preview = orch.preview_table(
            ":events",
            count=3,
            column_configs=[ColumnConfig(name=":value", generator="integer", params={"min_value": 7, "max_value": 7})],
        )
        assert preview == [{":value": 7}] * 3
    assert database.read_bytes() == before
    with sqlite_connection(database) as db:
        for name, column, value in ((":events", ":value", 17), ("events", "value", 99)):
            assert db.execute(f"SELECT {quote_identifier(column)} FROM {quote_identifier(name)}").fetchall() == [
                (value,)
            ]
