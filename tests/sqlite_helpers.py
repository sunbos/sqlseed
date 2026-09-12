"""SQLite test connections with a transaction and deterministic cleanup."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@contextmanager
def sqlite_connection(database: str | Path, **options: Any) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on failure, and always close the connection."""
    connection = sqlite3.connect(database, **options)
    try:
        with connection:
            yield connection
    finally:
        connection.close()
