"""Compare adapter metadata with native SQLite operations, independently of models."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("adapter_type", [SQLAlchemyAdapter, RawSQLiteAdapter])
@pytest.mark.parametrize(
    "definition,allocated,nullable",
    [
        ("id INTEGER PRIMARY KEY)", True, False),
        ("id INTEGER PRIMARY KEY AUTOINCREMENT)", True, False),
        ("id INTEGER,PRIMARY KEY(id DESC))", True, False),
        ("id INTEGER PRIMARY KEY DESC)", False, True),
        ("id INTEGER PRIMARY KEY DESC NOT NULL)", False, False),
        ("id INTEGER PRIMARY KEY) WITHOUT ROWID", False, False),
        ("id INT PRIMARY KEY)", False, True),
        ("id INTEGER,other INTEGER,PRIMARY KEY(id,other))", False, True),
    ],
)
def test_primary_key_metadata_matches_native_default_insert(
    tmp_path: Path,
    adapter_type: type[SQLAlchemyAdapter] | type[RawSQLiteAdapter],
    definition: str,
    allocated: bool,
    nullable: bool,
) -> None:
    path = tmp_path / "pk.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(" + definition)
        if allocated or nullable:
            db.execute("INSERT INTO items DEFAULT VALUES")
            value = db.execute("SELECT id FROM items").fetchone()[0]
            assert (value is not None) is allocated
        else:
            with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
                db.execute("INSERT INTO items DEFAULT VALUES")
    with adapter_type() as adapter:
        adapter.connect(str(path))
        column = adapter.get_column_info("items")[0]
        assert column.is_rowid_alias is allocated
        assert column.nullable is nullable


@pytest.mark.parametrize("adapter_type", [SQLAlchemyAdapter, RawSQLiteAdapter])
def test_partial_index_marker_survives_reflection(
    tmp_path: Path,
    adapter_type: type[SQLAlchemyAdapter] | type[RawSQLiteAdapter],
) -> None:
    path = tmp_path / "partial.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE items(kind TEXT,archived INTEGER,reference TEXT);"
            "CREATE UNIQUE INDEX active ON items(kind) WHERE archived=0;"
            "CREATE UNIQUE INDEX full ON items(reference);"
            "INSERT INTO items VALUES('same',1,'a'),('same',1,'b');"
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute("INSERT INTO items VALUES('different',1,'a')")
    with adapter_type() as adapter:
        adapter.connect(str(path))
        indexes = {index.name: index for index in adapter.get_index_info("items")}
        assert indexes["active"].unique and indexes["active"].is_partial
        assert indexes["full"].unique and not indexes["full"].is_partial
        if adapter_type is SQLAlchemyAdapter:
            assert indexes["active"].predicate == "archived=0"
        assert indexes["full"].predicate is None
        assert all(not index.is_partial for index in adapter.get_unique_constraints("items"))


@pytest.mark.parametrize("adapter_type", [SQLAlchemyAdapter, RawSQLiteAdapter])
def test_table_aliases_preserve_metadata_after_canonical_lookup(
    tmp_path: Path,
    adapter_type: type[SQLAlchemyAdapter] | type[RawSQLiteAdapter],
) -> None:
    path = tmp_path / "aliases.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE parents(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE CHECK(length(code)>0));"
            "CREATE INDEX codes ON parents(code);"
            "INSERT INTO PARENTS(code) VALUES('first');"
        )
        assert db.execute("SELECT id FROM PaReNtS").fetchall() == [(1,)]
    with adapter_type() as adapter:
        adapter.connect(str(path))
        for name in ["parents", "PARENTS", "PaReNtS"]:
            columns = adapter.get_column_info(name)
            assert [column.name for column in columns] == ["id", "code"]
            assert columns[0].is_autoincrement and columns[0].is_rowid_alias
            assert adapter.get_primary_keys(name) == ["id"]
            assert "codes" in {index.name for index in adapter.get_index_info(name)}
            assert adapter.get_check_constraints(name)
        assert adapter.batch_insert("PARENTS", iter([{"code": "second"}])) == 1
        assert adapter.batch_insert("PaReNtS", iter([{"code": "third"}])) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id,code FROM parents ORDER BY id").fetchall() == [
            (1, "first"),
            (2, "second"),
            (3, "third"),
        ]
