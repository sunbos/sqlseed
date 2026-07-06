"""Database adapter protocol and core data structure definitions.

Defines the runtime-checkable ``DatabaseAdapter`` protocol, as well as
schema metadata dataclasses for columns, foreign keys, and indexes,
providing a unified interface contract for all adapter implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(frozen=True)
class ColumnInfo:
    """Column metadata snapshot.

    Contains column name, type, nullability, default value, primary key, autoincrement,
    and computed/generated flags, returned by adapter ``get_column_info`` for use by the
    mapper and constraint checks.
    """

    name: str
    type: str
    nullable: bool
    default: Any
    is_primary_key: bool
    is_autoincrement: bool
    is_computed: bool = False


@dataclass(frozen=True)
class ForeignKeyInfo:
    """Foreign key relationship information.

    Describes that ``column`` of the current table references ``ref_column`` of the ``ref_table`` table,
    used for dependency ordering and reference value generation.
    """

    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class IndexInfo:
    """Index metadata.

    Contains the index name, owning table, covered columns tuple, and uniqueness flag,
    used for constraint inference and performance hints.
    """

    name: str
    table: str
    columns: tuple[str, ...]
    unique: bool


@dataclass(frozen=True)
class CheckConstraintInfo:
    """CHECK constraint metadata.

    Describes a table-level CHECK constraint by its raw SQL expression and the
    columns it references. Used by the AI plugin to convey business rules
    (e.g., ``sale_price >= cost_price``, ``status IN ('a','b','c')``) to the
    LLM so it can pick appropriate generators or ``derive_from`` expressions.

    Attributes:
        name: Constraint name (may be empty for unnamed constraints).
        table: Owning table name.
        columns: Tuple of column names referenced in the check expression.
            Empty tuple when the parser could not extract column references
            (the LLM still sees the raw ``expression`` in that case).
        expression: Raw CHECK constraint SQL expression (e.g.,
            ``"sale_price >= cost_price"``, ``"status IN ('a','b','c')"``).
    """

    name: str
    table: str
    columns: tuple[str, ...]
    expression: str


@runtime_checkable
class DatabaseAdapter(Protocol):
    """Database adapter protocol.

    Phase 1 adds optional dialect and bulk_optimizer attributes.
    The existing RawSQLiteAdapter does not yet implement these two attributes;
    upper-layer code checks support via ``hasattr(adapter, "dialect")``.
    Phase 2 introduces SQLAlchemyAdapter which fully implements these two attributes.

    Note: Protocol attributes participate in mypy type checking, so they are not declared here.
    Instead, they are explicitly implemented in SQLAlchemyAdapter and detected at runtime via hasattr().
    """

    def connect(self, db_path: str) -> None:
        """Connect to the database at the given path (SQLite file or database URL)."""

    def close(self) -> None:
        """Close the database connection and release underlying resources."""

    def get_table_names(self) -> list[str]:
        """Return the names of all tables in the connected database."""

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        """Return column metadata for every column of the given table."""

    def get_primary_keys(self, table_name: str) -> list[str]:
        """Return the primary key column names for the given table."""

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        """Return foreign key metadata for every foreign key of the given table."""

    def get_row_count(self, table_name: str) -> int:
        """Return the total number of rows in the given table."""

    def get_column_values(self, table_name: str, column_name: str, limit: int = 1000) -> list[Any]:
        """Return up to ``limit`` distinct values of the given column from the table."""

    def get_index_info(self, table_name: str) -> list[IndexInfo]:
        """Return index metadata for every index defined on the given table."""

    def get_unique_constraints(self, table_name: str) -> list[IndexInfo]:
        """Return UNIQUE constraint metadata for every UNIQUE constraint on the given table.

        This includes table-level ``UNIQUE(col1, col2)`` constraints that are NOT
        returned by ``get_index_info`` (SQLite creates auto-indexes for these, but
        SQLAlchemy's ``inspector.get_indexes`` excludes auto-indexes). Single-column
        and multi-column UNIQUE constraints are both returned.
        """

    def get_check_constraints(self, table_name: str) -> list[CheckConstraintInfo]:
        """Return CHECK constraint metadata for every CHECK on the given table.

        Implementations should return the raw SQL expression so the AI plugin
        can convey business rules to the LLM. May return an empty list for
        backends that do not expose CHECK constraints (e.g., older SQLite
        versions without ``sqlite_master`` parsing support).
        """

    def get_sample_rows(
        self,
        table_name: str,
        limit: int = 5,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` sample rows from the table, optionally projected to ``columns``."""

    def batch_insert(
        self,
        table_name: str,
        data: Iterator[dict[str, Any]],
        batch_size: int = 5000,
    ) -> int:
        """Insert rows yielded by ``data`` in batches and return the number of rows inserted."""

    def clear_table(self, table_name: str) -> None:
        """Delete all rows from the given table."""

    def optimize_for_bulk_write(self, expected_rows: int | None = None) -> None:
        """Apply bulk-write optimizations (e.g., PRAGMAs) before a large insert."""

    def restore_settings(self) -> None:
        """Restore database settings previously changed by ``optimize_for_bulk_write``."""

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        """Execute a SQL statement with optional parameters and return the cursor."""

    def __enter__(self) -> DatabaseAdapter: ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None: ...
