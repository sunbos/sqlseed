"""Shared utility functions for database adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.database._protocol import ColumnInfo, IndexInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlseed.database._bulk_optimizer import BulkWriteOptimizer
    from sqlseed.database.optimizer import PragmaOptimizer


def fetch_index_info(
    execute_fn: Callable[..., Any],
    table_name: str,
) -> list[IndexInfo]:
    """Get index information for a table.

    Queries all indexes and their columns of the specified table via PRAGMA index_list and PRAGMA index_info.

    Args:
        execute_fn: SQL execution function that returns a cursor with a fetchall method.
        table_name: Target table name.

    Returns:
        A list of IndexInfo for all indexes of the table.
    """
    safe_table = quote_identifier(table_name)
    rows = execute_fn(f"PRAGMA index_list({safe_table})").fetchall()
    result: list[IndexInfo] = []
    for row in rows:
        idx_name = row[1]
        is_unique = bool(row[2])
        col_rows = execute_fn(f"PRAGMA index_info({quote_identifier(idx_name)})").fetchall()
        columns = tuple(cr[2] for cr in col_rows if cr[2] is not None)
        result.append(IndexInfo(name=idx_name, table=table_name, columns=columns, unique=is_unique))
    return result


def fetch_sample_rows(
    execute_fn: Callable[..., Any],
    columns: list[ColumnInfo],
    table_name: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Get sample rows from a table.

    Args:
        execute_fn: SQL execution function that supports parameterized queries.
        columns: Column info list, determines the SELECT column order and the keys of the result dict.
        table_name: Target table name.
        limit: Maximum number of rows to return, default 5.

    Returns:
        A list of dicts keyed by column names with row values.
    """
    safe_table = quote_identifier(table_name)
    col_names = [quote_identifier(c.name) for c in columns]
    cols_sql = ", ".join(col_names)
    rows = execute_fn(f"SELECT {cols_sql} FROM {safe_table} LIMIT ?", [limit]).fetchall()
    col_name_list = [c.name for c in columns]
    return [dict(zip(col_name_list, row, strict=True)) for row in rows]


def batch_insert_rows(
    data: Iterator[dict[str, Any]],
    batch_size: int,
    insert_batch_fn: Callable[[list[dict[str, Any]]], int],
) -> int:
    """Insert data rows in batches.

    Groups rows produced by the iterator by batch_size, calls insert_batch_fn for each batch to write,
    and triggers a write for the last batch even when it is smaller than batch_size.

    Args:
        data: Row data iterator, each row is a dict mapping column names to values.
        batch_size: Maximum number of rows per batch.
        insert_batch_fn: Callback that actually writes a batch of data,
            returns the number of rows inserted in that batch.

    Returns:
        Total number of inserted rows.
    """
    inserted = 0
    batch: list[dict[str, Any]] = []
    for row in data:
        batch.append(row)
        if len(batch) >= batch_size:
            inserted += insert_batch_fn(batch)
            batch = []
    if batch:
        inserted += insert_batch_fn(batch)
    return inserted


def apply_bulk_optimize(
    optimizer: BulkWriteOptimizer | PragmaOptimizer | None,
    expected_rows: int | None = None,
) -> None:
    """Apply bulk write optimization.

    When optimizer is not None, first calls preserve() to save the current configuration,
    then calls optimize(expected_rows) to apply the optimization strategy.
    This function works for both PRAGMA and SET style optimizers.

    Args:
        optimizer: Bulk write optimizer instance, can be None.
        expected_rows: Expected number of rows to write, used to select the optimization level; uses default when None.
    """
    if optimizer is not None:
        optimizer.preserve()
        optimizer.optimize(expected_rows)


def apply_bulk_restore(
    optimizer: BulkWriteOptimizer | PragmaOptimizer | None,
) -> None:
    """Restore the database configuration prior to optimization.

    When optimizer is not None, calls restore() to restore the configuration saved by preserve().
    Typically used in pair with apply_bulk_optimize.

    Args:
        optimizer: Bulk write optimizer instance, can be None.
    """
    if optimizer is not None:
        optimizer.restore()
