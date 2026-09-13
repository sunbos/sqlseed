"""Real PostgreSQL JSON/JSONB and temporal values pass through typed bindings."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import JSON, null

import sqlseed
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.assertions import assert_empty

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration


@pytest.fixture(name="typed_pg_adapter")
def fixture_typed_pg_adapter(pg_url: str) -> Iterator[SQLAlchemyAdapter]:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(pg_url)
        adapter.execute(
            "CREATE TABLE typed_value_events (id INTEGER PRIMARY KEY, payload JSON, document JSONB, raw TEXT, "
            "day DATE, moment TIMESTAMP, instant TIMESTAMP WITH TIME ZONE, "
            "clock TIME, zoned_clock TIME WITH TIME ZONE)"
        ).close()
        try:
            yield adapter
        finally:
            adapter.execute("DROP TABLE typed_value_events").close()


@pytest.mark.parametrize("batch_size", [1, 20])
def test_pg_json_documents_round_trip_once(typed_pg_adapter: SQLAlchemyAdapter, batch_size: int) -> None:
    documents = [
        {"n": 7, "nested": [True, None]},
        [1, "null"],
        "literal",
        '{"n": 7}',
        "null",
        12,
        1.25,
        True,
        False,
        None,
    ]
    encoded = [json.dumps(value) for value in documents]
    rows = [{"id": i, "payload": value, "document": value, "raw": value} for i, value in enumerate(encoded)]
    assert typed_pg_adapter.batch_insert("typed_value_events", iter(rows), batch_size) == len(rows)
    cursor = typed_pg_adapter.execute(
        "SELECT payload, document, raw, payload IS NULL, document IS NULL FROM typed_value_events ORDER BY id"
    )
    try:
        actual = cursor.fetchall()
    finally:
        cursor.close()
    assert [(payload, document) for payload, document, _, _, _ in actual] == [(value, value) for value in documents]
    assert [raw for _, _, raw, _, _ in actual] == encoded
    assert not any(payload_null or document_null for _, _, _, payload_null, document_null in actual)
    for value in encoded:
        assert typed_pg_adapter._key_exists("typed_value_events", {"document": value})
    for column in ("payload", "document"):
        assert [
            json.loads(value) for value in typed_pg_adapter.get_column_values("typed_value_events", column)
        ] == documents
        assert [
            json.loads(row[column]) for row in typed_pg_adapter.get_sample_rows("typed_value_events", limit=20)
        ] == documents
        pairs = typed_pg_adapter._get_column_pairs("typed_value_events", column, "id")
        assert [(json.loads(value), index) for value, index in pairs] == [
            (value, i) for i, value in enumerate(documents)
        ]
        for index, value in enumerate(documents):
            document = typed_pg_adapter._lookup_value("typed_value_events", column, index, "id")
            assert json.loads(document) == value


def test_pg_native_json_and_sql_null(typed_pg_adapter: SQLAlchemyAdapter) -> None:
    values = [{"n": 7}, [1, 2], 4, 1.25, True, False, None, JSON.NULL, null()]
    rows = [{"id": i, "payload": value, "document": value} for i, value in enumerate(values)]
    assert typed_pg_adapter.batch_insert("typed_value_events", iter(rows)) == len(rows)
    cursor = typed_pg_adapter.execute("SELECT payload, document FROM typed_value_events ORDER BY id")
    try:
        actual = cursor.fetchall()
    finally:
        cursor.close()
    expected = [*values[:7], None, None]
    assert actual == [(value, value) for value in expected]
    cursor = typed_pg_adapter.execute(
        "SELECT id, payload IS NULL, document IS NULL FROM typed_value_events WHERE id>=6 ORDER BY id"
    )
    try:
        assert cursor.fetchall() == [(6, False, False), (7, False, False), (8, True, True)]
    finally:
        cursor.close()
    assert typed_pg_adapter._lookup_value("typed_value_events", "payload", 6, "id") == "null"
    assert typed_pg_adapter._lookup_value("typed_value_events", "payload", 8, "id") is None


@pytest.mark.parametrize("batch_size", [1, 20])
def test_pg_temporal_objects_and_iso_strings_round_trip(typed_pg_adapter: SQLAlchemyAdapter, batch_size: int) -> None:
    offset = timezone(timedelta(hours=8))
    native = {
        "day": date(2026, 9, 13),
        "moment": datetime(2026, 9, 13, 12, 34, 56, 123456),
        "instant": datetime(2026, 9, 13, 12, 34, 56, 123456, offset),
        "clock": time(12, 34, 56, 123456),
        "zoned_clock": time(12, 34, 56, 123456, offset),
    }
    encoded = {name: value.isoformat() for name, value in native.items()}
    utc = {**encoded, "instant": "2026-09-13T04:34:56.123456Z", "zoned_clock": "04:34:56.123456Z"}
    rows = [{"id": i, **value} for i, value in enumerate([native, encoded, utc])]
    assert typed_pg_adapter.batch_insert("typed_value_events", iter(rows), batch_size) == 3
    cursor = typed_pg_adapter.execute(
        "SELECT day, moment, instant, clock, zoned_clock FROM typed_value_events ORDER BY id"
    )
    try:
        actual = cursor.fetchall()
    finally:
        cursor.close()
    assert actual == [tuple(native.values())] * 3
    assert actual[0][2].utcoffset() is not None
    assert actual[0][4].utcoffset() == timedelta(hours=8)
    assert actual[2][4].utcoffset() == timedelta(0)
    assert typed_pg_adapter._key_exists("typed_value_events", encoded)
    assert typed_pg_adapter._lookup_value("typed_value_events", "day", encoded["moment"], "moment") == native["day"]


@pytest.mark.parametrize(
    ("column", "valid", "invalid", "type_name"),
    [
        ("payload", "{}", "{broken", "JSON"),
        ("document", "{}", "not JSON", "JSONB"),
        ("document", "{}", '{"n": NaN}', "JSONB"),
        ("document", {}, {"n": float("inf")}, "JSONB"),
        ("day", date(2026, 9, 13), "2026-02-30", "DATE"),
        ("moment", datetime(2026, 9, 13), "invalid", "TIMESTAMP"),
        ("clock", time(12), "25:00:00", "TIME"),
    ],
)
def test_pg_invalid_typed_value_rolls_back_prior_batch(
    typed_pg_adapter: SQLAlchemyAdapter, column: str, valid: Any, invalid: Any, type_name: str
) -> None:
    rows = [{"id": 1, column: valid}, {"id": 2, column: invalid}]
    with pytest.raises(ValueError, match=rf"Invalid {type_name} value for column '{column}'"):
        typed_pg_adapter.batch_insert("typed_value_events", iter(rows), batch_size=1)
    assert typed_pg_adapter.get_row_count("typed_value_events") == 0


@pytest.mark.parametrize("document", ['"hello"', '"123"', '"null"', "null", '[1,"123",null]', '{"n":7}'])
def test_pg_jsonb_parent_pool_retains_document_semantics(pg_url: str, document: str) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(pg_url)
        adapter.execute("CREATE TABLE typed_jsonb_parents (code JSONB PRIMARY KEY)").close()
        try:
            adapter.execute(
                "CREATE TABLE typed_jsonb_children (id SERIAL PRIMARY KEY, "
                "code JSONB NOT NULL REFERENCES typed_jsonb_parents(code), copied JSONB NOT NULL)"
            ).close()
            parent_result = sqlseed.fill(
                url=pg_url,
                table="typed_jsonb_parents",
                count=1,
                provider="base",
                optimize_pragma=False,
                columns={"code": {"generator": "choice", "choices": [document]}},
            )
            assert_empty(parent_result.errors, list)
            assert parent_result.count == 1
            child_result = sqlseed.fill(
                url=pg_url,
                table="typed_jsonb_children",
                count=3,
                provider="base",
                seed=42,
                optimize_pragma=False,
                columns={
                    "copied": {
                        "derive_from": "code",
                        "expression": "lookup('typed_jsonb_parents', 'code', value, 'code')",
                    }
                },
            )
            assert_empty(child_result.errors, list)
            assert child_result.count == 3
            cursor = adapter.execute(
                "SELECT code, copied, code IS NULL, copied IS NULL FROM typed_jsonb_children ORDER BY id"
            )
            try:
                assert cursor.fetchall() == [(json.loads(document), json.loads(document), False, False)] * 3
            finally:
                cursor.close()
        finally:
            adapter.execute("DROP TABLE IF EXISTS typed_jsonb_children").close()
            adapter.execute("DROP TABLE typed_jsonb_parents").close()
