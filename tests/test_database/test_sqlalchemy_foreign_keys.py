"""SQLite connections must enforce foreign keys before the first pooled use."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(name="fk_adapter", params=["path", "url"])
def fixture_fk_adapter(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[SQLAlchemyAdapter]:
    db_path = tmp_path / "foreign_keys.db"
    with sqlite_connection(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE parents (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE TABLE children (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parents(id) ON DELETE RESTRICT
            );
            INSERT INTO parents DEFAULT VALUES;
            INSERT INTO children VALUES (1, 1);
            """
        )
    target = f"sqlite:///{db_path}" if request.param == "url" else str(db_path)
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(target)
        yield adapter


@pytest.mark.parametrize("recreate_pool", [False, True], ids=["initial-pool", "recreated-pool"])
def test_pool_connections_reject_orphan_insert(fk_adapter: SQLAlchemyAdapter, recreate_pool: bool) -> None:
    if recreate_pool:
        # Pool replacement creates new DBAPI connections after initial reflection.
        fk_adapter._get_engine().dispose()
    rows = iter([{"id": 2, "parent_id": 999}])
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        fk_adapter.batch_insert("children", rows)

    assert fk_adapter.get_row_count("children") == 1
    assert fk_adapter.execute("PRAGMA foreign_key_check").fetchall() == []


def test_first_pooled_connection_restricts_parent_clear(fk_adapter: SQLAlchemyAdapter) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        fk_adapter.clear_table("parents")

    assert fk_adapter.get_row_count("parents") == 1
    assert fk_adapter.get_row_count("children") == 1
    assert fk_adapter.execute("PRAGMA foreign_key_check").fetchall() == []
