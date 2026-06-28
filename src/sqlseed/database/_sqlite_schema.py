"""SQLite-specific schema introspection helpers.

Provides AUTOINCREMENT detection by parsing the CREATE TABLE SQL stored in
SQLite's ``sqlite_master`` catalog table. Extracted from adapter implementations
to avoid code duplication (DRY principle) and to keep all SQLite-specific
introspection logic within the database layer.

Other databases (PostgreSQL, etc.) are not supported here —
``detect_sqlite_autoincrement`` relies on SQLite's ``sqlite_master`` catalog table
and SQLite-specific ``AUTOINCREMENT`` keyword semantics. PG autoincrement
detection is handled by the ``PostgresDialect`` implementation.
"""

from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


def _split_sql_definitions(sql: str) -> list[str]:
    """Extract individual column or constraint definitions from a CREATE TABLE statement.

    Splits on commas at bracket depth 0, so that commas inside type definitions
    (e.g. ``DECIMAL(10,2)``) or constraints (e.g. ``CHECK(x IN (1,2,3))``)
    are not treated as separators.
    """
    start = sql.find("(")
    end = sql.rfind(")")
    if start == -1 or end == -1:
        return []
    content = sql[start + 1 : end]

    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in content:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())
    return parts


def detect_sqlite_autoincrement(
    execute_fn: Callable[..., Any],
    table_name: str,
    column_name: str,
) -> bool:
    """Detect whether a column is declared as INTEGER PRIMARY KEY AUTOINCREMENT.

    Works with both ``sqlite-utils`` ``Database.execute()`` and raw
    ``sqlite3.Connection.execute()``.

    Args:
        execute_fn: A callable that executes SQL and returns a cursor-like
                    object with a ``.fetchone()`` method.
        table_name: Name of the table to inspect.
        column_name: Name of the column to check.

    Returns:
        ``True`` if the column is declared as ``INTEGER PRIMARY KEY AUTOINCREMENT``.
    """
    try:
        result = execute_fn(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            [table_name],
        )
        row = result.fetchone() if hasattr(result, "fetchone") else result
        if row and row[0]:
            sql_upper = row[0].upper()
            # Fast path: if AUTOINCREMENT keyword is absent, no need to parse further.
            if "AUTOINCREMENT" not in sql_upper:
                return False
            col_upper = column_name.upper()
            # Use bracket-aware splitter so DECIMAL(10,2) / CHECK(x IN (1,2,3))
            # are not split on their internal commas.
            for part in _split_sql_definitions(sql_upper):
                if (
                    re.search(rf"\b{re.escape(col_upper)}\b", part)
                    and "INTEGER" in part
                    and "PRIMARY" in part
                    and "AUTOINCREMENT" in part
                ):
                    return True
    except (ValueError, OSError, sqlite3.Error):
        logger.debug("Failed to detect autoincrement", table=table_name, column=column_name)
    return False
