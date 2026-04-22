from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    default: Any
    is_primary_key: bool
    is_autoincrement: bool


@dataclass(frozen=True)
class ForeignKeyInfo:
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class IndexInfo:
    name: str
    table: str
    columns: list[str]
    unique: bool


@runtime_checkable
class DatabaseAdapter(Protocol):
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

    def __enter__(self) -> DatabaseAdapter: ...

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None: ...
