"""A transaction-bound production adapter keeps multi-call SQLite work atomic."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


def database(tmp_path: Path) -> tuple[Path, SQLAlchemyAdapter]:
    path = tmp_path / "atomic.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            "CREATE TABLE parents(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE);"
            "CREATE TABLE children(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parents(id));"
            "INSERT INTO parents(id,code) VALUES(40,'old');INSERT INTO children VALUES(1,40);"
        )
    adapter = SQLAlchemyAdapter()
    adapter.connect(str(path))
    return path, adapter


def test_transaction_queries_and_insert_calls_share_uncommitted_rows(tmp_path: Path) -> None:
    path, adapter = database(tmp_path)
    try:
        with adapter.transaction():
            adapter.execute('DELETE FROM "children"').close()
            adapter.execute('DELETE FROM "parents"').close()
            assert adapter.get_row_count("parents") == 0
            adapter.batch_insert("parents", iter([{"code": "new"}]))
            parent = adapter.get_column_values("parents", "id")[0]
            assert parent == 41
            assert adapter.get_sample_rows("parents")[0]["code"] == "new"
            assert adapter.get_column_info("parents")[0].is_autoincrement
            adapter.batch_insert("children", iter([{"parent_id": parent}]))
            adapter.execute('UPDATE "parents" SET "code" = ?', ("updated",)).close()
            with closing(sqlite3.connect(path)) as db, db:
                assert db.execute("SELECT code FROM parents").fetchall() == [("old",)]
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("SELECT id,code FROM parents").fetchall() == [(41, "updated")]
            assert db.execute("SELECT parent_id FROM children").fetchall() == [(41,)]
    finally:
        adapter.close()


def test_late_batch_failure_rolls_back_deletes_rows_and_sequence_reset(tmp_path: Path) -> None:
    path, adapter = database(tmp_path)
    optimizer = adapter.bulk_optimizer
    try:
        with pytest.raises(IntegrityError), adapter.transaction():
            assert adapter.bulk_optimizer is None
            adapter.optimize_for_bulk_write(20000)
            adapter.execute('DELETE FROM "children"').close()
            adapter.clear_table("parents")
            adapter.batch_insert("parents", iter([{"code": "new"}]))
            adapter.batch_insert("parents", iter([{"code": "new"}]))
        assert adapter.bulk_optimizer is optimizer
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("SELECT id,code FROM parents").fetchall() == [(40, "old")]
            assert db.execute("SELECT * FROM children").fetchall() == [(1, 40)]
            assert db.execute("SELECT seq FROM sqlite_sequence WHERE name='parents'").fetchone()[0] == 40
        assert adapter.get_row_count("parents") == 1
    finally:
        adapter.close()


def test_nested_transaction_is_rejected_and_outer_transaction_can_rollback(tmp_path: Path) -> None:
    _, adapter = database(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="already"), adapter.transaction():
            adapter.execute('DELETE FROM "children"').close()
            with adapter.transaction():
                pass
        assert adapter.get_row_count("children") == 1
    finally:
        adapter.close()


def test_deferred_foreign_key_failure_on_commit_restores_original_data(tmp_path: Path) -> None:
    path, adapter = database(tmp_path)
    try:
        adapter.execute("DROP TABLE children").close()
        adapter.execute(
            "CREATE TABLE children(id INTEGER PRIMARY KEY, "
            "parent_id INTEGER REFERENCES parents(id) DEFERRABLE INITIALLY DEFERRED)"
        ).close()
        adapter.execute("INSERT INTO children VALUES(1,40)").close()
        with pytest.raises(IntegrityError), adapter.transaction():
            adapter.execute("DELETE FROM children").close()
            adapter.execute("DELETE FROM parents").close()
            assert adapter.batch_insert("children", iter([{"id": 2, "parent_id": 999}])) == 1
            assert adapter.get_column_values("children", "parent_id") == [999]
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("SELECT * FROM children").fetchall() == [(1, 40)]
            assert db.execute("SELECT * FROM parents").fetchall() == [(40, "old")]
        assert adapter.get_row_count("parents") == 1
    finally:
        adapter.close()
