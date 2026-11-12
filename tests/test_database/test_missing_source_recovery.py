"""A negative column-value lookup must not hide a later-created source."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("catalog_name", ["source", "Source"])
def test_column_values_refresh_cached_absence(tmp_path: Path, catalog_name: str) -> None:
    db_path = tmp_path / "adapter.sqlite"
    with closing(sqlite3.connect(db_path)) as conn, SQLAlchemyAdapter() as adapter:
        conn.execute("CREATE TABLE sentinel(value TEXT)")
        conn.execute("INSERT INTO sentinel VALUES('original')")
        conn.commit()
        adapter.connect(str(db_path))
        assert adapter.get_column_values("source", "id") == []
        assert adapter.get_column_values("source", "id") == []
        # Fixed test-only catalog variants, not untrusted SQL identifiers.
        conn.execute(f'CREATE TABLE "{catalog_name}"(id INTEGER PRIMARY KEY)')
        conn.execute(f'INSERT INTO "{catalog_name}" VALUES(101)')
        conn.commit()
        before = db_path.read_bytes()
        assert adapter.get_column_values("source", "id") == [101]
        assert db_path.read_bytes() == before
        conn.execute(f'INSERT INTO "{catalog_name}" VALUES(102)')
        conn.commit()
        assert adapter.get_column_values("source", "id") == [101, 102]
        assert conn.execute("SELECT * FROM sentinel").fetchall() == [("original",)]
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
