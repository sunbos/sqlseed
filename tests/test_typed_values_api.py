"""Public generation APIs retain JSON document and ISO date configuration semantics."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import yaml

import sqlseed
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def test_fill_json_generator_stores_a_queryable_document(tmp_path: Path) -> None:
    path = tmp_path / "generated_json.db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, payload JSON NOT NULL, raw TEXT NOT NULL)")
    specification = {"generator": "json", "schema": {"type": "object", "properties": {"n": {"type": "integer"}}}}
    result = sqlseed.fill(
        str(path),
        table="events",
        count=3,
        provider="base",
        seed=42,
        optimize_pragma=False,
        columns={"payload": specification, "raw": specification},
    )
    assert_empty(result.errors, list)
    assert result.count == 3
    with sqlite_connection(path) as connection:
        rows = connection.execute("SELECT json_type(payload), json_extract(payload, '$.n'), raw FROM events").fetchall()
    assert len(rows) == 3
    assert all(
        kind == "object" and isinstance(number, int) and isinstance(json.loads(raw), dict) for kind, number, raw in rows
    )


def test_fill_from_yaml_accepts_iso_date_choices(tmp_path: Path) -> None:
    path = tmp_path / "generated_dates.db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, holiday DATE NOT NULL)")
    config_path = tmp_path / "generate.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "db_path": str(path),
                "provider": "base",
                "tables": [
                    {
                        "name": "events",
                        "count": 3,
                        "columns": [
                            {
                                "name": "holiday",
                                "generator": "choice",
                                "params": {"choices": ["2026-01-01", "2026-12-25"]},
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    results = sqlseed.fill_from_config(str(config_path))
    assert len(results) == 1
    assert_empty(results[0].errors, list)
    assert results[0].count == 3
    with sqlite_connection(path) as connection:
        rows = connection.execute("SELECT holiday FROM events").fetchall()
    assert len(rows) == 3
    assert all(value in {"2026-01-01", "2026-12-25"} for (value,) in rows)


@pytest.mark.parametrize("document", ['"hello"', '"123"', '"null"', "null", '[1,"123",null]', '{"n":7}', "123", "true"])
@pytest.mark.parametrize("parent_source", ["generated", "existing"])
@pytest.mark.parametrize("composite", [False, True])
def test_fill_json_foreign_key_preserves_parent_document(
    tmp_path: Path, document: str, parent_source: str, composite: bool
) -> None:
    path = tmp_path / "json_fk.db"
    unique_key = "code, slot" if composite else "code"
    foreign_key = (
        "FOREIGN KEY(code, slot) REFERENCES parents(code, slot)"
        if composite
        else "FOREIGN KEY(code) REFERENCES parents(code)"
    )
    with sqlite_connection(path) as connection:
        connection.execute(f"CREATE TABLE parents (code JSON NOT NULL, slot INTEGER NOT NULL, UNIQUE({unique_key}))")
        connection.execute(
            f"CREATE TABLE children (id INTEGER PRIMARY KEY, code JSON NOT NULL, slot INTEGER NOT NULL, {foreign_key})"
        )
        if parent_source == "existing":
            connection.execute("INSERT INTO parents VALUES (?, 1)", (document,))
    if parent_source == "generated":
        parent_result = sqlseed.fill(
            str(path),
            table="parents",
            count=1,
            provider="base",
            optimize_pragma=False,
            columns={
                "code": {"generator": "choice", "choices": [document]},
                "slot": {"generator": "choice", "choices": [1]},
            },
        )
        assert_empty(parent_result.errors, list)
        assert parent_result.count == 1
    result = sqlseed.fill(
        str(path),
        table="children",
        count=3,
        provider="base",
        seed=42,
        optimize_pragma=False,
        columns={"slot": {"generator": "choice", "choices": [1]}},
    )
    assert_empty(result.errors, list)
    assert result.count == 3
    with sqlite_connection(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        parents = connection.execute("SELECT CAST(code AS TEXT), json_type(code) FROM parents").fetchall()
        children = connection.execute("SELECT CAST(code AS TEXT), json_type(code) FROM children").fetchall()
    assert parents[0][0] == document
    assert children == parents * 3


@pytest.mark.parametrize("document", ['"hello"', '"123"', '"null"', "null", '[1,"123",null]', '{"n":7}'])
def test_derived_json_lookup_preserves_document(tmp_path: Path, document: str) -> None:
    path = tmp_path / "json_lookup.db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, payload JSON NOT NULL)")
        connection.execute("INSERT INTO sources VALUES (1, ?)", (document,))
        connection.execute(
            "CREATE TABLE copies (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, payload JSON NOT NULL)"
        )
    result = sqlseed.fill(
        str(path),
        table="copies",
        count=3,
        provider="base",
        optimize_pragma=False,
        columns={
            "source_id": {"generator": "choice", "choices": [1]},
            "payload": {"derive_from": "source_id", "expression": "lookup('sources', 'payload', value)"},
        },
    )
    assert_empty(result.errors, list)
    assert result.count == 3
    with sqlite_connection(path) as connection:
        rows = connection.execute("SELECT CAST(payload AS TEXT) FROM copies").fetchall()
    assert rows == [(document,)] * 3
