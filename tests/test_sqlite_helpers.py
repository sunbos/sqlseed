"""Verify the shared SQLite transaction and connection lifecycle."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def test_success_commits_and_closes_connection(tmp_path: Path) -> None:
    path = tmp_path / "committed.db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE items(value INTEGER)")
        connection.execute("INSERT INTO items VALUES (7)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with sqlite_connection(path) as reader:
        assert reader.execute("SELECT value FROM items").fetchall() == [(7,)]


@pytest.mark.parametrize("failure_type", [RuntimeError, KeyboardInterrupt])
def test_body_failure_rolls_back_and_closes(tmp_path: Path, failure_type: type[BaseException]) -> None:
    path = tmp_path / "rolled-back.db"
    with sqlite_connection(path) as setup:
        setup.execute("CREATE TABLE items(value INTEGER)")
    with pytest.raises(failure_type, match="abort"), sqlite_connection(path) as connection:
        connection.execute("INSERT INTO items VALUES (9)")
        raise failure_type("abort")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with sqlite_connection(path) as reader:
        assert reader.execute("SELECT COUNT(*) FROM items").fetchone() == (0,)


def test_failed_commit_rolls_back_and_closes(tmp_path: Path) -> None:
    path = tmp_path / "failed-commit.db"
    with sqlite_connection(path) as setup:
        setup.executescript(
            "CREATE TABLE parents(id INTEGER PRIMARY KEY);"
            "CREATE TABLE children(parent_id INTEGER REFERENCES parents(id) DEFERRABLE INITIALLY DEFERRED);"
        )
    with pytest.raises(sqlite3.IntegrityError), sqlite_connection(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("INSERT INTO children VALUES (99)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with sqlite_connection(path) as reader:
        assert reader.execute("SELECT COUNT(*) FROM children").fetchone() == (0,)


def test_connection_options_preserve_uri_and_autocommit(tmp_path: Path) -> None:
    path = tmp_path / "autocommit.db"
    with sqlite_connection(path.as_uri(), uri=True, isolation_level=None) as connection:
        assert connection.isolation_level is None
        connection.execute("CREATE TABLE items(value INTEGER)")
        connection.execute("INSERT INTO items VALUES (11)")
        with sqlite_connection(path.as_uri() + "?mode=ro", uri=True) as reader:
            assert reader.execute("SELECT value FROM items").fetchone() == (11,)
