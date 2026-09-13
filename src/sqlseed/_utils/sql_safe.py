"""SQL identifier safety utilities — three-layer defense against injection.

This module provides three complementary layers of protection:

1. **Validate** (``validate_table_name``): sanity-checks the identifier against
   a safe-pattern regex and warns on unusual names. Does not reject by default —
   names with special characters are still allowed because layer 2 will quote them.

2. **Quote** (``quote_identifier``): wraps the identifier in double quotes and
   escapes internal double quotes by doubling them (``"`` → ``""``). This is the
   SQL standard quoting rule and is supported by SQLite and PostgreSQL.

3. **Build** (``build_insert_sql``): composes parameterized INSERT statements
   using quoted identifiers and ``?`` placeholders for values.

Dangerous-character rejection (``_DANGEROUS_CHARS_RE``):
    The characters ``;``, ``\\n``, ``\\r``, and ``'`` are rejected outright because
    they can terminate or alter SQL statements even inside double-quoted
    identifiers in some edge cases. The hyphen ``-`` is **not** rejected because
    once the identifier is wrapped in double quotes, ``-`` is a legal character
    in SQLite and PostgreSQL (e.g. ``"my-table"``). The ``--`` comment sequence
cannot be triggered because the ``-`` is inside a quoted identifier.
"""

from __future__ import annotations

import re

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)

_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_]\w*$")
_DANGEROUS_CHARS_RE = re.compile(r"[\x00;\n\r']")


def _sanitize_identifier(name: str) -> str:
    if not name or not name.strip():
        raise ValueError("SQL identifier cannot be empty")
    if _DANGEROUS_CHARS_RE.search(name):
        raise ValueError(f"SQL identifier '{name}' contains dangerous characters and is rejected")
    return name


def quote_identifier(name: str) -> str:
    """Safely escape a SQL identifier (table name, column name).

    Wraps the identifier in double quotes and replaces internal double quotes
    with two double quotes (``"`` → ``""``), per the SQL standard. This is
    supported by SQLite and PostgreSQL.

    Rejects identifiers containing dangerous characters (``;``, newlines, ``'``).
    The hyphen ``-`` is allowed because it is safe inside double-quoted identifiers.
    """
    name = _sanitize_identifier(name)
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def validate_table_name(name: str) -> str:
    """Validate and quote a table name.

    Performs basic legality checks in addition to quoting. Warns about table
    names containing special characters (non-alphanumeric/underscore) so that
    downstream issues are easier to diagnose.
    """
    if not _SAFE_IDENTIFIER_RE.match(name):
        logger.warning("Table name contains special characters", table_name=name)
    return quote_identifier(name)


def build_insert_sql(table_name: str, column_names: list[str]) -> str:
    """Build a safe INSERT statement with quoted identifiers and parameter placeholders.

    Returns:
        ``INSERT INTO "table" ("col1", "col2") VALUES (?, ?)``
    """
    if not column_names:
        raise ValueError("Cannot build INSERT SQL: column_names is empty")
    safe_table = quote_identifier(table_name)
    safe_columns = ", ".join(quote_identifier(col) for col in column_names)
    placeholders = ", ".join(["?"] * len(column_names))
    return f"INSERT INTO {safe_table} ({safe_columns}) VALUES ({placeholders})"
