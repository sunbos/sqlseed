from __future__ import annotations

import contextlib
import sqlite3
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import build_insert_sql, quote_identifier, validate_table_name
from sqlseed.database._base_adapter import BaseSQLiteAdapter
from sqlseed.database._helpers import batch_insert_rows
from sqlseed.database._protocol import ColumnInfo, ForeignKeyInfo
from sqlseed.database.optimizer import PragmaOptimizer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = get_logger(__name__)


class RawSQLiteAdapter(BaseSQLiteAdapter):
    def __init__(self) -> None:
        super().__init__()
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        assert self._conn is not None, "Database not connected. Call connect() first."
        return self._conn

    def _get_execute_fn(self) -> Callable[..., Any]:
        return self.conn.execute

    def connect(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._optimizer = PragmaOptimizer(
            execute_fn=self._execute_pragma,
            fetch_pragma_fn=self._fetch_pragma,
        )
        logger.debug("Connected to database via raw sqlite3", db_path=db_path)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.debug("Closed raw sqlite3 connection", db_path=self._db_path)

    def get_table_names(self) -> list[str]:
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        return [row[0] for row in cursor.fetchall()]

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        validate_table_name(table_name)
        pks = set(self.get_primary_keys(table_name))

        cursor = self.conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
        result: list[ColumnInfo] = []
        for row in cursor.fetchall():
            _, name, col_type, notnull, default_val, _ = row
            if default_val == "NULL":
                default_val = None
            is_pk_flag = name in pks
            is_autoincrement = is_pk_flag and self._is_autoincrement(table_name, name)
            result.append(
                ColumnInfo(
                    name=name,
                    type=col_type.upper() if col_type else "TEXT",
                    nullable=not is_pk_flag and not notnull,
                    default=default_val,
                    is_primary_key=is_pk_flag,
                    is_autoincrement=is_autoincrement,
                )
            )
        return result

    def get_primary_keys(self, table_name: str) -> list[str]:
        validate_table_name(table_name)
        cursor = self.conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
        pks: list[str] = []
        for row in cursor.fetchall():
            _, name, _, _, _, is_pk = row
            if is_pk:
                pks.append(name)
        return pks

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        validate_table_name(table_name)
        cursor = self.conn.execute(f"PRAGMA foreign_key_list({quote_identifier(table_name)})")
        result: list[ForeignKeyInfo] = []
        for row in cursor.fetchall():
            _, _, ref_table, from_col, to_col, *_ = row
            result.append(
                ForeignKeyInfo(
                    column=from_col,
                    ref_table=ref_table,
                    ref_column=to_col,
                )
            )
        return result

    def get_row_count(self, table_name: str) -> int:
        validate_table_name(table_name)
        safe_table = quote_identifier(table_name)
        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {safe_table}")
        return int(cursor.fetchone()[0])

    def batch_insert(
        self,
        table_name: str,
        data: Iterator[dict[str, Any]],
        batch_size: int = 5000,
    ) -> int:
        validate_table_name(table_name)
        return batch_insert_rows(data, batch_size, lambda b: self._insert_batch(table_name, b))

    def _insert_batch(self, table_name: str, batch: list[dict[str, Any]]) -> int:
        if not batch:
            return 0
        column_names = list(batch[0].keys())
        sql = build_insert_sql(table_name, column_names)
        values = [tuple(row[col] for col in column_names) for row in batch]
        self.conn.executemany(sql, values)
        self.conn.commit()
        return len(batch)

    def clear_table(self, table_name: str) -> None:
        validate_table_name(table_name)
        safe_table = quote_identifier(table_name)
        self.conn.execute(f"DELETE FROM {safe_table}")
        with contextlib.suppress(Exception):
            self.conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", [table_name])
        self.conn.commit()
        logger.debug("Cleared table", table_name=table_name)

    def restore_settings(self) -> None:
        super().restore_settings()
        self.conn.commit()

    def _execute_pragma(self, sql: str) -> None:
        self.conn.execute(sql)

    def _fetch_pragma(self, name: str) -> Any:
        cursor = self.conn.execute(f"PRAGMA {name}")
        row = cursor.fetchone()
        return row[0] if row else None
