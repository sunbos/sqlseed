"""
Shared database schema helper utilities.

Extracted from adapter implementations to avoid code duplication (DRY principle).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def detect_autoincrement(
    execute_fn: Any,
    table_name: str,
    column_name: str,
) -> bool:
    """
    Detect whether a column is AUTOINCREMENT by inspecting the CREATE TABLE SQL.

    Works with both sqlite-utils Database.execute() and raw sqlite3 Connection.execute().

    Args:
        execute_fn: A callable that executes SQL and returns a cursor-like object
                    with a .fetchone() method.
        table_name: Name of the table.
        column_name: Name of the column to check.

    Returns:
        True if the column is declared as INTEGER PRIMARY KEY AUTOINCREMENT.
    """
    try:
        result = execute_fn(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            [table_name],
        )
        row = result.fetchone() if hasattr(result, "fetchone") else result
        if row and row[0]:
            sql_upper = row[0].upper()
            if "AUTOINCREMENT" not in sql_upper:
                return False
            col_upper = column_name.upper()
            for part in sql_upper.split(","):
                stripped = part.strip()
                if col_upper in stripped and "INTEGER" in stripped and "PRIMARY" in stripped:
                    return True
    except Exception:
        logger.debug("Failed to detect autoincrement", extra={"table": table_name, "column": column_name})
    return False
