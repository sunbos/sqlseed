from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.database._protocol import ColumnInfo, IndexInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def fetch_index_info(
    execute_fn: Callable[..., Any],
    table_name: str,
) -> list[IndexInfo]:
    safe_table = quote_identifier(table_name)
    rows = execute_fn(f"PRAGMA index_list({safe_table})").fetchall()
    result: list[IndexInfo] = []
    for row in rows:
        idx_name = row[1]
        is_unique = bool(row[2])
        if idx_name.startswith("sqlite_autoindex_"):
            continue
        col_rows = execute_fn(f"PRAGMA index_info({quote_identifier(idx_name)})").fetchall()
        columns = [cr[2] for cr in col_rows if cr[2] is not None]
        result.append(IndexInfo(name=idx_name, table=table_name, columns=columns, unique=is_unique))
    return result


def fetch_sample_rows(
    execute_fn: Callable[..., Any],
    columns: list[ColumnInfo],
    table_name: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    safe_table = quote_identifier(table_name)
    col_names = [quote_identifier(c.name) for c in columns]
    cols_sql = ", ".join(col_names)
    rows = execute_fn(f"SELECT {cols_sql} FROM {safe_table} LIMIT ?", [limit]).fetchall()
    col_name_list = [c.name for c in columns]
    return [dict(zip(col_name_list, row, strict=False)) for row in rows]


def batch_insert_rows(
    data: Iterator[dict[str, Any]],
    batch_size: int,
    insert_batch_fn: Callable[[list[dict[str, Any]]], int],
) -> int:
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


def apply_pragma_optimize(
    optimizer: Any,
    expected_rows: int | None = None,
) -> None:
    if optimizer is not None:
        optimizer.preserve()
        optimizer.optimize(expected_rows)


def apply_pragma_restore(optimizer: Any) -> None:
    if optimizer is not None:
        optimizer.restore()
