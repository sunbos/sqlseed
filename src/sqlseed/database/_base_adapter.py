"""Base raw SQLite adapter providing shared logic (context manager, PRAGMA optimization, SQL utilities)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from typing_extensions import Self

from sqlseed._utils.logger import get_logger
from sqlseed._utils.schema_helpers import detect_autoincrement
from sqlseed._utils.sql_safe import quote_identifier, validate_table_name
from sqlseed.database._helpers import (
    apply_bulk_optimize,
    apply_bulk_restore,
    fetch_index_info,
    fetch_sample_rows,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed.database._protocol import ColumnInfo, IndexInfo
    from sqlseed.database.optimizer import PragmaOptimizer

logger = get_logger(__name__)


class BaseRawSQLiteAdapter:
    """Base raw SQLite adapter.

    Provides shared logic for native sqlite3-based adapters, including:
    - Context manager protocol (__enter__/__exit__)
    - Bulk write optimization (preserve/optimize/restore delegated to helpers)
    - Common SQL utility methods (index info, sample rows, column values, autoincrement detection)

    Subclasses must implement: _get_execute_fn, get_column_info, close and other abstract methods.
    """

    def __init__(self) -> None:
        """Initialize shared base state.

        Subclasses should call this via super().__init__() before initializing their own attributes.
        """
        self._optimizer: PragmaOptimizer | None = None
        self._db_path: str = ""

    def _get_execute_fn(self) -> Callable[..., Any]:
        """Return the SQL execution function.

        Subclasses must implement this method, returning a callable with signature (sql, params) -> cursor.

        Raises:
            NotImplementedError: Raised directly when subclasses do not implement it.
        """
        raise NotImplementedError

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        """Execute a SQL statement with parameters.

        Args:
            sql: The SQL statement to execute.
            params: Tuple of parameters for parameterized queries.

        Returns:
            The cursor object.
        """
        return self._get_execute_fn()(sql, params)

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        """Get column information for a table.

        Subclasses must implement this method, returning a list of ColumnInfo for all columns in the table.

        Args:
            table_name: Target table name.

        Raises:
            NotImplementedError: Raised directly when subclasses do not implement it.
        """
        raise NotImplementedError

    def close(self) -> None:
        """Close the database connection and release resources.

        Subclasses must implement this method.

        Raises:
            NotImplementedError: Raised directly when subclasses do not implement it.
        """
        raise NotImplementedError

    def get_index_info(self, table_name: str) -> list[IndexInfo]:
        """Get index information for a table.

        Args:
            table_name: Target table name.

        Returns:
            A list of IndexInfo for all indexes of the table.
        """
        validate_table_name(table_name)
        return fetch_index_info(self._get_execute_fn(), table_name)

    def get_sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Get sample rows from a table.

        Args:
            table_name: Target table name.
            limit: Maximum number of rows to return, default 5.

        Returns:
            A list of dicts keyed by column names with row values.
        """
        validate_table_name(table_name)
        columns = self.get_column_info(table_name)
        return fetch_sample_rows(self._get_execute_fn(), columns, table_name, limit)

    def get_column_values(self, table_name: str, column_name: str, limit: int = 1000) -> list[Any]:
        """Get all values of a specified column.

        Args:
            table_name: Target table name.
            column_name: Target column name.
            limit: Maximum number of rows to return, default 1000.

        Returns:
            A list of values for that column.
        """
        validate_table_name(table_name)
        safe_table = quote_identifier(table_name)
        safe_column = quote_identifier(column_name)
        sql = f"SELECT {safe_column} FROM {safe_table} LIMIT ?"
        rows = self._get_execute_fn()(sql, [limit]).fetchall()
        return [row[0] for row in rows]

    def optimize_for_bulk_write(self, expected_rows: int | None = None) -> None:
        """Apply bulk write optimization.

        Delegates to apply_bulk_optimize, which saves the current configuration
        before applying the optimization strategy.

        Args:
            expected_rows: Expected number of rows to write, used to select the
                optimization level; uses default when None.
        """
        apply_bulk_optimize(self._optimizer, expected_rows)

    def restore_settings(self) -> None:
        """Restore the database configuration prior to optimization.

        Delegates to apply_bulk_restore, used in pair with optimize_for_bulk_write.
        """
        apply_bulk_restore(self._optimizer)

    def _is_autoincrement(self, table_name: str, column_name: str) -> bool:
        """Detect whether a column is an autoincrement column.

        Args:
            table_name: Target table name.
            column_name: Target column name.

        Returns:
            True if it is an autoincrement column, False otherwise.
        """
        return detect_autoincrement(self._get_execute_fn(), table_name, column_name)

    def __enter__(self) -> Self:
        """Enter the context, returning self."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit the context, automatically closing the connection."""
        self.close()
