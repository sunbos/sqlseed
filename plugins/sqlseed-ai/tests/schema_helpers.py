"""Construct real schema snapshots for AI validation and repair tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def snapshot_from_ddl(path: Path, ddl: str) -> SchemaSnapshot:
    with sqlite_connection(path) as connection:
        connection.executescript(ddl)
    return SchemaSnapshot(db_path=str(path))
