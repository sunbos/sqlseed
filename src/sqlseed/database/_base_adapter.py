from __future__ import annotations

from typing import TYPE_CHECKING, Any

from typing_extensions import Self

from sqlseed._utils.logger import get_logger
from sqlseed._utils.schema_helpers import detect_autoincrement
from sqlseed._utils.sql_safe import quote_identifier, validate_table_name
from sqlseed.database._helpers import (
    apply_pragma_optimize,
    apply_pragma_restore,
    fetch_index_info,
    fetch_sample_rows,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed.database._protocol import ColumnInfo, IndexInfo
    from sqlseed.database.optimizer import PragmaOptimizer

logger = get_logger(__name__)


class BaseSQLiteAdapter:
    def __init__(self) -> None:
        self._optimizer: PragmaOptimizer | None = None
        self._db_path: str = ""

    def _get_execute_fn(self) -> Callable[..., Any]:
        raise NotImplementedError

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def get_index_info(self, table_name: str) -> list[IndexInfo]:
        validate_table_name(table_name)
        return fetch_index_info(self._get_execute_fn(), table_name)

    def get_sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        validate_table_name(table_name)
        columns = self.get_column_info(table_name)
        return fetch_sample_rows(self._get_execute_fn(), columns, table_name, limit)

    def get_column_values(self, table_name: str, column_name: str, limit: int = 1000) -> list[Any]:
        validate_table_name(table_name)
        safe_table = quote_identifier(table_name)
        safe_column = quote_identifier(column_name)
        sql = f"SELECT {safe_column} FROM {safe_table} LIMIT ?"
        rows = self._get_execute_fn()(sql, [limit]).fetchall()
        return [row[0] for row in rows]

    def optimize_for_bulk_write(self, expected_rows: int | None = None) -> None:
        apply_pragma_optimize(self._optimizer, expected_rows)

    def restore_settings(self) -> None:
        apply_pragma_restore(self._optimizer)

    def _is_autoincrement(self, table_name: str, column_name: str) -> bool:
        return detect_autoincrement(self._get_execute_fn(), table_name, column_name)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()
