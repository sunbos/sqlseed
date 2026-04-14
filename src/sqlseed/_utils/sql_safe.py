from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def quote_identifier(name: str) -> str:
    """
    Safely escape a SQL identifier (table name, column name).

    Uses SQLite's double-quote escaping rules:
    - Wrap the identifier in double quotes
    - Replace internal double quotes with two double quotes
    """
    if not name or not name.strip():
        raise ValueError("SQL identifier cannot be empty")
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def validate_table_name(name: str) -> str:
    """
    Validate and escape a table name.

    Performs basic legality checks in addition to escaping.
    Warns about table names containing special characters.
    """
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        logger.warning("Table name '%s' contains special characters and will be quoted", name)
    return quote_identifier(name)


def build_insert_sql(table_name: str, column_names: list[str]) -> str:
    """
    构建安全的 INSERT SQL 语句。

    Returns:
        INSERT INTO "table" ("col1", "col2") VALUES (?, ?)
    """
    safe_table = quote_identifier(table_name)
    safe_columns = ", ".join(quote_identifier(col) for col in column_names)
    placeholders = ", ".join(["?"] * len(column_names))
    return f"INSERT INTO {safe_table} ({safe_columns}) VALUES ({placeholders})"
