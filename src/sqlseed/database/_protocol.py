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

    Contains column name, type, nullability, default value, primary key and autoincrement flags,
    returned by adapter ``get_column_info`` for use by the mapper and constraint checks.
    """

    name: str
    type: str
    nullable: bool
    default: Any
    is_primary_key: bool
    is_autoincrement: bool


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

    def connect(self, db_path: str) -> None: ...

    def close(self) -> None: ...

    def get_table_names(self) -> list[str]: ...

    def get_column_info(self, table_name: str) -> list[ColumnInfo]: ...

    def get_primary_keys(self, table_name: str) -> list[str]: ...

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]: ...

    def get_row_count(self, table_name: str) -> int: ...

    def get_column_values(self, table_name: str, column_name: str, limit: int = 1000) -> list[Any]: ...

    def get_index_info(self, table_name: str) -> list[IndexInfo]: ...

    def get_sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]: ...

    def batch_insert(
        self,
        table_name: str,
        data: Iterator[dict[str, Any]],
        batch_size: int = 5000,
    ) -> int: ...

    def clear_table(self, table_name: str) -> None: ...

    def optimize_for_bulk_write(self, expected_rows: int | None = None) -> None: ...

    def restore_settings(self) -> None: ...

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any: ...

    def __enter__(self) -> DatabaseAdapter: ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None: ...
