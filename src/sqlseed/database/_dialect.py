"""Database dialect abstraction layer.

Encapsulates database-specific behavior (type normalization, autoincrement detection, identifier quoting),
so upper-layer code does not need to be aware of whether the underlying database is SQLite, PostgreSQL, or MySQL.

Phase 1 implements SQLiteDialect; phase 3 adds PostgresDialect; MySQLDialect is left for future work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable


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
        ...

    def detect_autoincrement(self, column_info: dict[str, Any]) -> bool:
        """Detect whether a column is autoincrement.

        SQLite: parse CREATE TABLE to find AUTOINCREMENT
        PG: detect SERIAL / IDENTITY / nextval()
        """
        ...

    def reset_autoincrement(self, execute_fn: Callable[..., Any], table_name: str) -> None:
        """Reset the autoincrement counter.

        SQLite: DELETE FROM sqlite_sequence
        PG: TRUNCATE ... RESTART IDENTITY / ALTER SEQUENCE
        MySQL: ALTER TABLE ... AUTO_INCREMENT = 1
        """
        ...

    def quote_identifier(self, name: str) -> str:
        """Quote an identifier.

        SQLite/PG: "name"
        MySQL: `name`
        """
        ...


class SQLiteDialect:
    """SQLite dialect implementation.

    Autoincrement detection is delegated to ``sqlseed._utils.schema_helpers.detect_autoincrement``,
    which parses the CREATE TABLE SQL in ``sqlite_master``.
    """

    name = "sqlite"

    def normalize_type(self, raw_type: str) -> str:
        """SQLite types are already in normalized uppercase form."""
        return raw_type.upper() if raw_type else "TEXT"

    def detect_autoincrement(self, column_info: dict[str, Any]) -> bool:
        """SQLite autoincrement detection requires parsing the CREATE TABLE SQL.

        Not implemented here in phase 1; completed by SQLAlchemyAdapter/RawSQLiteAdapter
        via ``schema_helpers.detect_autoincrement``.
        This method is retained for interface consistency and returns False as a placeholder.
        """
        return False

    def reset_autoincrement(self, execute_fn: Callable[..., Any], table_name: str) -> None:
        """Reset the SQLite autoincrement sequence: DELETE FROM sqlite_sequence."""
        execute_fn("DELETE FROM sqlite_sequence WHERE name = ?", [table_name])

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

    def detect_autoincrement(self, column_info: dict[str, Any]) -> bool:
        """Triple detection of PG autoincrement columns.

        Args:
            column_info: Column info dict returned by the SQLAlchemy inspector,
                         may contain ``identity``, ``default``, ``autoincrement`` fields.

        Returns:
            True if the column is IDENTITY / SERIAL / BIGSERIAL.
        """
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
            for _col, seq_name in rows:
                if seq_name:
                    execute_fn(f"ALTER SEQUENCE {seq_name} RESTART WITH 1")
        except Exception:
            # Sequence reset failure should not block the main clear_table flow
            pass

    def quote_identifier(self, name: str) -> str:
        """PG uses double quotes to quote identifiers (same as SQLite)."""
        escaped = name.replace('"', '""')
        return f'"{escaped}"'


__all__ = ["Dialect", "PostgresDialect", "SQLiteDialect"]
