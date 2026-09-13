"""Typed insertion preserves JSON documents and accepts ISO temporal inputs."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import JSON, Column, Integer, MetaData, Table, create_engine, null, select

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter, SQLAlchemyBatchInserter
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("batch_size", [1, 20])
def test_json_documents_round_trip_once_without_changing_text(tmp_path: Path, batch_size: int) -> None:
    path = tmp_path / "json.db"
    documents = [
        {"n": 7, "nested": [True, None, "null"]},
        [1, {"n": 2}],
        "literal string",
        '{"looks": "like a document"}',
        "null",
        12,
        1.25,
        True,
        False,
        None,
    ]
    encoded = [json.dumps(value) for value in documents]
    rows = [{"id": index, "payload": value, "raw": value} for index, value in enumerate(encoded)]
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        adapter.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, payload JSON, raw TEXT)").close()
        assert adapter.batch_insert("events", iter(rows), batch_size) == len(rows)
        for index, value in enumerate(encoded):
            assert adapter._key_exists("events", {"payload": value})
            assert adapter._lookup_value("events", "payload", index, "id") == value
        assert adapter.get_column_values("events", "payload", limit=20) == encoded
        assert [row["payload"] for row in adapter.get_sample_rows("events", limit=20)] == encoded
        assert adapter._get_column_pairs("events", "payload", "id") == [(value, i) for i, value in enumerate(encoded)]
    with sqlite_connection(path) as connection:
        actual = connection.execute(
            "SELECT CAST(payload AS TEXT), raw, payload IS NULL FROM events ORDER BY id"
        ).fetchall()
        assert [json.loads(value) for value, _, _ in actual] == documents
        assert [raw for _, raw, _ in actual] == encoded
        assert not any(is_null for _, _, is_null in actual)
        assert connection.execute("SELECT json_extract(payload, '$.n') FROM events WHERE id=0").fetchone() == (7,)
        kinds = connection.execute("SELECT json_type(payload) FROM events ORDER BY id").fetchall()
        assert [kind for (kind,) in kinds] == [
            "object",
            "array",
            "text",
            "text",
            "text",
            "integer",
            "real",
            "true",
            "false",
            "null",
        ]
    assert [row["payload"] for row in rows] == encoded


def test_native_json_values_and_explicit_sql_null_keep_their_meaning(tmp_path: Path) -> None:
    path = tmp_path / "native_json.db"
    values = [{"n": 3}, [1, 2], 4, 1.25, True, False, None]
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        adapter.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, payload JSON)").close()
        assert adapter.batch_insert("events", iter({"id": i, "payload": value} for i, value in enumerate(values))) == 7
        assert adapter.batch_insert("events", iter([{"id": 7, "payload": null()}])) == 1
        assert adapter.batch_insert("events", iter([{"id": 8, "payload": JSON.NULL}])) == 1
        for value in values:
            assert adapter._key_exists("events", {"payload": value})
        assert adapter._key_exists("events", {"id": 7, "payload": null()})
        assert adapter._lookup_value("events", "payload", 6, "id") == "null"
        assert adapter._lookup_value("events", "payload", 7, "id") is None
    with sqlite_connection(path) as connection:
        rows = connection.execute("SELECT CAST(payload AS TEXT) FROM events WHERE id<7 ORDER BY id").fetchall()
        assert [json.loads(value) for (value,) in rows] == values
        assert connection.execute("SELECT payload IS NULL FROM events WHERE id=7").fetchone() == (1,)
        assert connection.execute("SELECT payload, payload IS NULL FROM events WHERE id=8").fetchone() == ("null", 0)


def test_serialized_json_null_is_independent_of_native_none_policy(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'json_null.db'}")
    table = Table(
        "events", MetaData(), Column("id", Integer, primary_key=True), Column("payload", JSON(none_as_null=True))
    )
    try:
        table.create(engine)
        rows = [{"id": index, "payload": value} for index, value in enumerate([None, "null", JSON.NULL, null()])]
        assert SQLAlchemyBatchInserter(engine, "events", table=table).insert(rows) == 4
        with engine.connect() as connection:
            result = connection.execute(select(table.c.payload.is_(None)).order_by(table.c.id)).scalars().all()
        assert result == [True, False, False, True]
    finally:
        engine.dispose()


@pytest.mark.parametrize("batch_size", [1, 20])
def test_iso_temporal_values_and_native_objects_round_trip(tmp_path: Path, batch_size: int) -> None:
    path = tmp_path / "temporal.db"
    native = {
        "day": date(2026, 9, 13),
        "moment": datetime(2026, 9, 13, 12, 34, 56, 123456),
        "clock": time(12, 34, 56, 123456),
    }
    encoded = {"day": "2026-09-13", "moment": "2026-09-13T12:34:56.123456", "clock": "12:34:56.123456"}
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        adapter.execute("CREATE TABLE events (day DATE, moment DATETIME, clock TIME)").close()
        assert adapter.batch_insert("events", iter([encoded, native, dict.fromkeys(native)]), batch_size) == 3
        assert adapter._key_exists("events", encoded)
        assert adapter._key_exists("events", native)
        assert adapter._lookup_value("events", "day", encoded["moment"], "moment") == native["day"]
    with sqlite_connection(path) as connection:
        rows = connection.execute("SELECT day, moment, clock FROM events ORDER BY rowid").fetchall()
        assert rows == [("2026-09-13", "2026-09-13 12:34:56.123456", "12:34:56.123456")] * 2 + [(None, None, None)]
    assert encoded["moment"] == "2026-09-13T12:34:56.123456"
    assert isinstance(native["moment"], datetime)


def test_iso_utc_strings_use_the_existing_sqlite_temporal_representation(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "utc.db"))
        adapter.execute("CREATE TABLE events (moment DATETIME, clock TIME)").close()
        values = {"moment": "2026-09-13T12:34:56.123456Z", "clock": "12:34:56.123456Z"}
        assert adapter.batch_insert("events", iter([values])) == 1
        assert adapter._key_exists("events", values)
        cursor = adapter.execute("SELECT moment, clock FROM events")
        try:
            # SQLite's typed SQLAlchemy temporal processors store naive values.
            assert cursor.fetchone() == ("2026-09-13 12:34:56.123456", "12:34:56.123456")
        finally:
            cursor.close()


@pytest.mark.parametrize(
    ("type_name", "valid", "invalid"),
    [
        ("JSON", '{"ok": true}', '{"broken":}'),
        ("JSON", "[]", "not JSON"),
        ("JSON", "[]", "NaN"),
        ("JSON", "[]", '{"n": Infinity}'),
        ("JSON", [], {"n": float("nan")}),
        ("JSON", [], b"{}"),
        ("DATE", date(2026, 9, 13), "2026-02-30"),
        ("DATE", date(2026, 9, 13), "2026-09-13T12:34:56"),
        ("DATE", date(2026, 9, 13), 123),
        ("DATETIME", datetime(2026, 9, 13), "2026-09-13T25:00:00"),
        ("DATETIME", datetime(2026, 9, 13), 123),
        ("TIME", time(12), "25:00:00"),
        ("TIME", time(12), "2026-09-13"),
        ("TIME", time(12), 123),
    ],
)
def test_invalid_typed_values_roll_back_prior_batches(tmp_path: Path, type_name: str, valid: Any, invalid: Any) -> None:
    path = tmp_path / "invalid.db"
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        adapter.execute(f"CREATE TABLE events (value {type_name})").close()
        with pytest.raises(ValueError, match=rf"Invalid {type_name} value for column 'value'"):
            adapter.batch_insert("events", iter([{"value": valid}, {"value": invalid}]), batch_size=1)
        assert adapter.get_row_count("events") == 0
