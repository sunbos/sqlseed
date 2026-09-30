"""Literal SQLite paths and nested URIs must address the intended real file."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from typing import TYPE_CHECKING
from urllib.parse import unquote

import pytest
from sqlalchemy.exc import OperationalError

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def _create_marker(path: Path, value: int) -> None:
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE marker(value INTEGER NOT NULL)")
        connection.execute("INSERT INTO marker VALUES(?)", (value,))


@pytest.mark.parametrize("name", ["orders %41.db", "数据 space %FF %2541 #.db"])
@pytest.mark.parametrize("kind", ["path", "url", "driver_url", "file_uri"])
def test_literal_percent_filename_reads_and_writes_only_the_requested_file(
    tmp_path: Path, name: str, kind: str
) -> None:
    expected = tmp_path / name
    decoded = tmp_path / unquote(name)
    _create_marker(expected, 7)
    _create_marker(decoded, 99)
    before = set(tmp_path.iterdir())
    targets = {
        "path": str(expected),
        "url": f"sqlite:///{expected}",
        "driver_url": f"sqlite+pysqlite:///{expected}",
        "file_uri": f"sqlite:///{expected.as_uri()}?uri=true&mode=rw",
    }
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(targets[kind])
        with closing(adapter.execute("SELECT value FROM marker")) as cursor:
            assert cursor.fetchall() == [(7,)]
        with closing(adapter.execute("INSERT INTO marker VALUES(?)", (8,))):
            pass
    with sqlite_connection(expected) as connection:
        assert connection.execute("SELECT value FROM marker ORDER BY value").fetchall() == [(7,), (8,)]
    with sqlite_connection(decoded) as connection:
        assert connection.execute("SELECT value FROM marker").fetchall() == [(99,)]
    assert set(tmp_path.iterdir()) == before


def test_file_uri_preserves_read_only_mode_and_dbapi_options(tmp_path: Path) -> None:
    path = tmp_path / "read only %41.db"
    _create_marker(path, 7)
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(f"sqlite:///{path.as_uri()}?uri=true&mode=ro&timeout=1.25")
        with closing(adapter.execute("SELECT value FROM marker")) as cursor:
            assert cursor.fetchall() == [(7,)]
        with closing(adapter.execute("PRAGMA busy_timeout")) as cursor:
            assert cursor.fetchall() == [(1250,)]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            adapter.execute("INSERT INTO marker VALUES(8)")
    with sqlite_connection(path) as connection:
        assert connection.execute("SELECT value FROM marker").fetchall() == [(7,)]


def test_file_uri_read_write_mode_does_not_create_a_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "absent %41.db"
    target = f"sqlite:///{path.as_uri()}?uri=true&mode=rw"
    with SQLAlchemyAdapter() as adapter, pytest.raises(OperationalError, match="unable to open database"):
        adapter.connect(target)
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(sys.platform == "win32", reason="Windows disallows ? in filenames")
def test_bare_path_with_question_mark_is_not_parsed_as_url_options(tmp_path: Path) -> None:
    path = tmp_path / "literal?mode=memory.db"
    _create_marker(path, 7)
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        with closing(adapter.execute("SELECT value FROM marker")) as cursor:
            assert cursor.fetchall() == [(7,)]
    assert list(tmp_path.iterdir()) == [path]
