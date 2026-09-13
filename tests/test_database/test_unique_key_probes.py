"""Unique key probes follow complete index definitions in real SQLite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed.database._unique_keys import get_unique_keys
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.assertions import assert_empty

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(name="unique_probe_adapter")
def fixture_unique_probe_adapter(tmp_path: Path) -> Iterator[SQLAlchemyAdapter]:
    """Keep these SQLite oracles independent of parent collector identities."""
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "unique_probe.db"))
        yield adapter


def test_unique_probes_preserve_distinct_index_collations(unique_probe_adapter: SQLAlchemyAdapter) -> None:
    db = unique_probe_adapter
    db.execute('CREATE TABLE nodes ("label key" TEXT, bucket INTEGER)').close()
    db.execute('CREATE UNIQUE INDEX binary_key ON nodes("label key" COLLATE BINARY, bucket)').close()
    db.execute('CREATE UNIQUE INDEX nocase_key ON nodes("label key" COLLATE NOCASE, bucket)').close()
    db.execute("INSERT INTO nodes VALUES (?, ?)", ("Alpha", 1)).close()

    results = {}
    for key in get_unique_keys(db, table_name="nodes"):
        cursor = db.execute(f"SELECT 1 FROM nodes WHERE {key.predicate(placeholder='?')}", ("alpha", 1))
        try:
            results[key.collations] = cursor.fetchone() is not None
        finally:
            cursor.close()
    assert results == {("BINARY", "BINARY"): False, ("NOCASE", "BINARY"): True}


def test_unique_probes_do_not_promote_partial_or_expression_indexes(unique_probe_adapter: SQLAlchemyAdapter) -> None:
    db = unique_probe_adapter
    db.execute("CREATE TABLE nodes (code TEXT, bucket INTEGER, active INTEGER)").close()
    db.execute("CREATE UNIQUE INDEX active_bucket ON nodes(bucket) WHERE active = 1").close()
    db.execute("CREATE UNIQUE INDEX folded_code ON nodes(bucket, lower(code))").close()
    db.execute("INSERT INTO nodes VALUES ('Alpha', 1, 0), ('Beta', 1, 0)").close()

    assert_empty(get_unique_keys(db, table_name="nodes"), list)
    cursor = db.execute("SELECT COUNT(*) FROM nodes WHERE bucket = 1")
    try:
        assert cursor.fetchone() == (2,)
    finally:
        cursor.close()
