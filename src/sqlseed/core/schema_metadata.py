"""Typed read boundary for optional adapter metadata.

Adapters and dialect extensions can fail with vendor-specific exceptions.
Consumers can distinguish an unavailable metadata operation from an empty
result without coupling their fallback policies to every database driver.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlseed._utils.sql_safe import quote_identifier

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlseed.database._protocol import CheckConstraintInfo, ColumnInfo, DatabaseAdapter


class SchemaMetadataError(RuntimeError):
    """An adapter could not supply a particular table's optional metadata."""

    def __init__(self, table_name: str, operation: str) -> None:
        self.table_name = table_name
        self.operation = operation
        super().__init__(f"Cannot read {operation} metadata for table {table_name!r}")


class SchemaMetadataReader:
    """Read metadata without choosing whether a caller should fall back or fail."""

    def __init__(self, adapter: DatabaseAdapter) -> None:
        self._adapter = adapter

    def columns(self, table_name: str) -> list[ColumnInfo]:
        """Materialize the adapter's column description in one read operation."""
        try:
            return list(self._adapter.get_column_info(table_name))
        except Exception as error:
            raise SchemaMetadataError(table_name, "columns") from error

    def checks(self, table_name: str) -> Iterator[CheckConstraintInfo]:
        """Yield available checks, preserving earlier items if later reads fail."""
        try:
            yield from self._adapter.get_check_constraints(table_name)
        except Exception as error:
            raise SchemaMetadataError(table_name, "checks") from error

    def sqlite_ddl(self, table_name: str) -> str:
        """Read the optional table DDL using a bound catalog lookup."""
        try:
            result = self._adapter.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            rows = result.fetchall() if hasattr(result, "fetchall") else []
            ddl = rows[0][0] if rows and rows[0] else ""
            return ddl if isinstance(ddl, str) else ""
        except Exception as error:
            raise SchemaMetadataError(table_name, "sqlite_ddl") from error

    def sqlite_index_predicates(self, table_name: str) -> Iterator[tuple[str, str]]:
        """Read textual partial-index annotations supplied by SQLite extensions."""
        try:
            result = self._adapter.execute(f"PRAGMA index_list({quote_identifier(table_name)})")
            rows = result.fetchall() if hasattr(result, "fetchall") else []
            for row in rows:
                if len(row) >= 5 and isinstance(partial := row[4], str) and partial.strip():
                    yield row[1], partial
        except Exception as error:
            raise SchemaMetadataError(table_name, "sqlite_index_predicates") from error
