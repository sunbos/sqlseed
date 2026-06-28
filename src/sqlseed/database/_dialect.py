"""Database dialect abstraction layer.

Encapsulates database-specific behavior (type normalization, autoincrement detection, identifier quoting),
so upper-layer code does not need to be aware of whether the underlying database is SQLite or PostgreSQL.

Phase 1 implements SQLiteDialect; phase 3 adds PostgresDialect.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from sqlalchemy.exc import SQLAlchemyError

from sqlseed._utils.logger import get_logger
from sqlseed.database._sqlite_schema import detect_sqlite_autoincrement

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


@runtime_checkable
class Dialect(Protocol):
    """Database dialect abstraction.

    Encapsulates database-specific behavior so upper-layer code does not need to be aware of the underlying dialect.
    """

    name: str

    def normalize_type(self, raw_type: str) -> str:
        """Normalize the database raw type name to sqlseed internal type.

        SQLite: "TEXT" -> "TEXT", "INTEGER" -> "INTEGER"
        PG: "character varying(255)" -> "VARCHAR(255)"
        """
        del raw_type
        raise NotImplementedError

    def detect_autoincrement(
        self,
        column_info: dict[str, Any],
        *,
        table_name: str,
        execute_fn: Callable[..., Any],
    ) -> bool:
        """Detect whether a column is autoincrement.

        SQLite: parse CREATE TABLE to find AUTOINCREMENT (uses execute_fn + table_name)
        PG: detect SERIAL / IDENTITY / nextval() (uses column_info only)

        Args:
            column_info: Column metadata dict from the SQLAlchemy inspector.
            table_name: Target table name (required by SQLite to query sqlite_master).
            execute_fn: Callable executing SQL with signature (sql, params) -> cursor
                (required by SQLite to query sqlite_master; ignored by PG).
        """
        del column_info, table_name, execute_fn
        raise NotImplementedError

    def reset_autoincrement(self, execute_fn: Callable[..., Any], table_name: str) -> None:
        """Reset the autoincrement counter.

        SQLite: DELETE FROM sqlite_sequence
        PG: TRUNCATE ... RESTART IDENTITY / ALTER SEQUENCE
        """
        del execute_fn, table_name

    def quote_identifier(self, name: str) -> str:
        """Quote an identifier.

        SQLite/PG: "name"
        """
        del name
        raise NotImplementedError


class SQLiteDialect:
    """SQLite dialect implementation.

    Autoincrement detection parses the CREATE TABLE SQL stored in
    ``sqlite_master`` via ``database._sqlite_schema.detect_sqlite_autoincrement``.
    """

    name = "sqlite"

    def normalize_type(self, raw_type: str) -> str:
        """SQLite types are already in normalized uppercase form."""
        return raw_type.upper() if raw_type else "TEXT"

    def detect_autoincrement(
        self,
        column_info: dict[str, Any],
        *,
        table_name: str,
        execute_fn: Callable[..., Any],
    ) -> bool:
        """SQLite autoincrement detection: parse CREATE TABLE SQL from sqlite_master.

        Args:
            column_info: Column metadata dict (uses ``column_info["name"]``).
            table_name: Target table name.
            execute_fn: Callable executing SQL with signature (sql, params) -> cursor.
        """
        return detect_sqlite_autoincrement(execute_fn, table_name, column_info["name"])

    def reset_autoincrement(self, execute_fn: Callable[..., Any], table_name: str) -> None:
        """Reset the SQLite autoincrement sequence: DELETE FROM sqlite_sequence.

        Silently skips when the table has no AUTOINCREMENT column (the
        ``sqlite_sequence`` table does not exist), which raises
        ``sqlite3.OperationalError``.
        """
        try:
            execute_fn("DELETE FROM sqlite_sequence WHERE name = ?", [table_name])
        except (sqlite3.Error, OSError):
            logger.debug("sqlite_sequence reset skipped", table_name=table_name)

    def quote_identifier(self, name: str) -> str:
        """SQLite uses double quotes to quote identifiers."""
        escaped = name.replace('"', '""')
        return f'"{escaped}"'


class PostgresDialect:
    """PostgreSQL dialect implementation.

    Autoincrement detection supports three PG autoincrement modes:
    - GENERATED ... AS IDENTITY (recommended for PG 10+)
    - SERIAL / BIGSERIAL (traditional mode, default contains nextval())
    - SQLAlchemy's autoincrement flag (integer PK inference)
    """

    name = "postgresql"

    def normalize_type(self, raw_type: str) -> str:
        """PG type normalization is delegated to TypeNormalizer (via _PG_TYPE_MAP)."""
        if not raw_type:
            return "TEXT"
        return raw_type.upper()

    def detect_autoincrement(
        self,
        column_info: dict[str, Any],
        *,
        table_name: str,
        execute_fn: Callable[..., Any],
    ) -> bool:
        """Triple detection of PG autoincrement columns.

        PG autoincrement metadata is fully available in ``column_info`` (returned
        by the SQLAlchemy inspector), so ``table_name`` and ``execute_fn`` are
        accepted for interface symmetry but not used.

        Args:
            column_info: Column info dict returned by the SQLAlchemy inspector,
                         may contain ``identity``, ``default``, ``autoincrement`` fields.
            table_name: Target table name (unused by PG).
            execute_fn: SQL execution callable (unused by PG).

        Returns:
            True if the column is IDENTITY / SERIAL / BIGSERIAL.
        """
        # PG autoincrement metadata is fully available in column_info; the
        # table_name and execute_fn kwargs exist only for interface symmetry
        # with other dialect implementations.
        del table_name, execute_fn
        # 1. GENERATED ... AS IDENTITY (PG 10+)
        if column_info.get("identity") is not None:
            return True
        # 2. SERIAL / BIGSERIAL: default value contains nextval('..._seq'::regclass)
        default = column_info.get("default")
        if default and "nextval" in str(default):
            return True
        # 3. SQLAlchemy's autoincrement flag (integer PK inference)
        return bool(column_info.get("autoincrement"))

    def reset_autoincrement(self, execute_fn: Callable[..., Any], table_name: str) -> None:
        """Reset the PG autoincrement sequence.

        PG has no global table like sqlite_sequence; the sequence name corresponding
        to the table must be queried before RESTART.
        For IDENTITY columns use ``ALTER TABLE ... RESTART IDENTITY`` (via TRUNCATE);
        for SERIAL columns use ``ALTER SEQUENCE ... RESTART WITH 1``.

        Args:
            execute_fn: Callable that executes SQL with signature ``(sql, params=None) -> cursor``.
            table_name: Table name.
        """
        # Query all sequence names of the table (SERIAL mode)
        # pg_get_serial_sequence returns the fully qualified name of the sequence
        try:
            cursor = execute_fn(
                "SELECT c.column_name, pg_get_serial_sequence(a.attrelid::regclass::text, c.column_name) "
                "FROM information_schema.columns c "
                "JOIN pg_attribute a ON a.attname = c.column_name "
                "WHERE c.table_name = %s AND c.table_schema = 'public'",
                [table_name],
            )
            rows = cursor.fetchall() if hasattr(cursor, "fetchall") else []
            for _, seq_name in rows:
                if seq_name:
                    # Quote each part of the fully qualified sequence name to prevent
                    # SQL injection and handle identifiers requiring quoting.
                    # pg_get_serial_sequence may return "schema.seq" or schema.seq.
                    parts = seq_name.split(".")
                    quoted_seq = ".".join(self.quote_identifier(p.strip('"')) for p in parts)
                    execute_fn(f"ALTER SEQUENCE {quoted_seq} RESTART WITH 1")
        except (SQLAlchemyError, OSError, ValueError, RuntimeError) as exc:
            # Sequence reset failure should not block the main clear_table flow,
            # but log it at debug level so failures are diagnosable rather than silent.
            logger.debug(
                "PG sequence reset failed; clear_table will continue",
                table=table_name,
                error=str(exc),
            )

    def quote_identifier(self, name: str) -> str:
        """PG uses double quotes to quote identifiers (same as SQLite)."""
        escaped = name.replace('"', '""')
        return f'"{escaped}"'


__all__ = ["Dialect", "PostgresDialect", "SQLiteDialect"]
