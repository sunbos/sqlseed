"""Expression indexes never imply uniqueness of their ordinary-column subset."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed import fill, preview
from sqlseed.core.schema import SchemaInferrer
from sqlseed.database._helpers import fetch_index_info
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

EXPRESSION_KEYS = ["bucket, lower(code)", "bucket, tag, lower(code)", "lower(code)"]
ADAPTERS = [SQLAlchemyAdapter, RawSQLiteAdapter]


def create_database(path: Path, key: str) -> None:
    """Prove same ordinary values can coexist under the full expression key."""
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, bucket INTEGER, tag INTEGER, code TEXT NOT NULL)")
        db.execute(f"CREATE UNIQUE INDEX expression_key ON items({key})")
        db.execute("INSERT INTO items VALUES(100, 7, 9, 'Alpha'), (101, 7, 9, 'Beta')")
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            db.execute("INSERT INTO items VALUES(102, 7, 9, 'alpha')")
        assert db.execute("SELECT COUNT(*) FROM items").fetchone() == (2,)


@pytest.mark.parametrize("adapter_type", ADAPTERS)
@pytest.mark.parametrize("key", EXPRESSION_KEYS)
def test_expression_key_is_not_truncated(tmp_path: Path, adapter_type: type, key: str) -> None:
    path = tmp_path / "expressions.sqlite"
    create_database(path, key)
    with adapter_type() as adapter:
        adapter.connect(str(path))
        indexes = fetch_index_info(adapter.execute, "items")
        assert len(indexes) == 1
        assert indexes[0].name == "expression_key"
        assert indexes[0].unique is True
        assert indexes[0].columns == ()
        schema = SchemaInferrer(adapter)
        assert schema.detect_unique_columns("items") == {"id"}
        assert_empty(schema.detect_composite_unique_constraints("items"), list)
        assert adapter.get_row_count("items") == 2


@pytest.mark.parametrize("adapter_type", ADAPTERS)
@pytest.mark.parametrize(
    ("definition", "columns", "partial", "singles", "composite"),
    [
        ("(bucket)", ("bucket",), False, {"id", "bucket"}, []),
        ("(bucket, tag)", ("bucket", "tag"), False, {"id"}, [["bucket", "tag"]]),
        ("(code COLLATE NOCASE)", ("code",), False, {"id", "code"}, []),
        ("(bucket) WHERE tag = 1", ("bucket",), True, {"id"}, []),
    ],
)
def test_complete_and_partial_index_controls(
    tmp_path: Path,
    adapter_type: type,
    definition: str,
    columns: tuple[str, ...],
    partial: bool,
    singles: set[str],
    composite: list[list[str]],
) -> None:
    path = tmp_path / "controls.sqlite"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, bucket INTEGER, tag INTEGER, code TEXT)")
        db.execute(f"CREATE UNIQUE INDEX ordinary_key ON items{definition}")
    with adapter_type() as adapter:
        adapter.connect(str(path))
        index = fetch_index_info(adapter.execute, "items")[0]
        assert index.columns == columns
        assert index.is_partial is partial
        schema = SchemaInferrer(adapter)
        assert schema.detect_unique_columns("items") == singles
        assert schema.detect_composite_unique_constraints("items") == composite


@pytest.mark.parametrize("key", EXPRESSION_KEYS)
def test_preview_and_fill_preserve_explicit_constant_columns(tmp_path: Path, key: str) -> None:
    path = tmp_path / "public-api.sqlite"
    create_database(path, key)
    columns = {
        "bucket": {"generator": "integer", "params": {"min_value": 7, "max_value": 7}},
        "tag": {"generator": "integer", "params": {"min_value": 9, "max_value": 9}},
        "code": {"generator": "uuid"},
    }
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = preview(str(path), table="items", count=4, columns=columns, provider="base", seed=42)
    assert len(rows) == 4
    assert [(row["bucket"], row["tag"]) for row in rows] == [(7, 9)] * 4
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    result = fill(
        str(path),
        table="items",
        count=4,
        columns=columns,
        provider="base",
        seed=42,
        batch_size=2,
        optimize_pragma=False,
        skip_ai=True,
    )
    assert result.count == 4
    assert result.batch_count == 2
    assert_empty(result.errors, list)
    with sqlite_connection(path) as db:
        stored = db.execute("SELECT id, bucket, tag, code FROM items ORDER BY id").fetchall()
        assert stored[:2] == [(100, 7, 9, "Alpha"), (101, 7, 9, "Beta")]
        assert len(stored) == 6
        assert [(row[1], row[2]) for row in stored] == [(7, 9)] * 6
        assert len({row[3].lower() for row in stored}) == 6
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
