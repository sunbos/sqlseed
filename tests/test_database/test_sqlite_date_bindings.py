"""SQLite date writes must work without the deprecated DBAPI adapters."""

from __future__ import annotations

import sqlite3
import warnings
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("batch_size", [1, 3])
def test_text_date_values_keep_precision_and_offset(tmp_path: Path, batch_size: int) -> None:
    path = tmp_path / "dates.db"
    values = [
        date(2026, 9, 11),
        datetime(2026, 9, 11, 12, 34, 56),
        datetime(2026, 9, 11, 12, 34, 56, 123456, timezone(timedelta(hours=8))),
    ]
    expected = ["2026-09-11", "2026-09-11 12:34:56", "2026-09-11 12:34:56.123456+08:00"]
    with SQLAlchemyAdapter() as adapter, warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        adapter.connect(str(path))
        adapter.execute("CREATE TABLE events (value TEXT UNIQUE, nullable TEXT)").close()
        assert adapter.batch_insert("events", iter({"value": value} for value in values), batch_size) == 3
        cursor = adapter.execute("SELECT value, nullable FROM events ORDER BY rowid")
        assert cursor.fetchall() == [(value, None) for value in expected]
        cursor.close()
        for value in values:
            assert adapter._key_exists("events", {"value": value})


def test_raw_date_bindings_work_inside_and_outside_transactions(tmp_path: Path) -> None:
    with SQLAlchemyAdapter() as adapter, warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        adapter.connect(str(tmp_path / "raw_dates.db"))
        adapter.execute("CREATE TABLE events (value TEXT)").close()
        adapter.execute("INSERT INTO events VALUES (?)", (date(2026, 9, 11),)).close()
        with adapter.transaction():
            adapter.execute("INSERT INTO events VALUES (?)", (datetime(2026, 9, 12, 1, 2, 3),)).close()
        cursor = adapter.execute("SELECT value FROM events ORDER BY rowid")
        assert cursor.fetchall() == [("2026-09-11",), ("2026-09-12 01:02:03",)]
        cursor.close()


def test_sqlalchemy_typed_dates_keep_their_bind_processors(tmp_path: Path) -> None:
    path = tmp_path / "typed_dates.db"
    adapters_before = sqlite3.adapters.copy()
    with SQLAlchemyAdapter() as adapter, warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        adapter.connect(str(path))
        adapter.execute("CREATE TABLE events (day DATE, moment DATETIME)").close()
        assert (
            adapter.batch_insert("events", iter([{"day": date(2026, 9, 11), "moment": datetime(2026, 9, 11, 1, 2, 3)}]))
            == 1
        )
        cursor = adapter.execute("SELECT day, moment FROM events")
        assert cursor.fetchone() == ("2026-09-11", "2026-09-11 01:02:03.000000")
        cursor.close()
        assert adapter._key_exists("events", {"day": date(2026, 9, 11), "moment": datetime(2026, 9, 11, 1, 2, 3)})
    assert sqlite3.adapters == adapters_before
