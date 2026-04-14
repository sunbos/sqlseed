from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from typing_extensions import Self

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import build_insert_sql, quote_identifier
from sqlseed.database._protocol import ColumnInfo, ForeignKeyInfo, IndexInfo
from sqlseed.database.optimizer import PragmaOptimizer

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = get_logger(__name__)


class RawSQLiteAdapter:
    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None
        self._optimizer: PragmaOptimizer | None = None
        self._db_path: str = ""

    @property
    def conn(self) -> sqlite3.Connection:
        assert self._conn is not None, "Database not connected. Call connect() first."
        return self._conn

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
        pks = set(self.get_primary_keys(table_name))
        fks = {fk.column for fk in self.get_foreign_keys(table_name)}

        cursor = self.conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
        result: list[ColumnInfo] = []
        for row in cursor.fetchall():
            _cid, name, col_type, notnull, default_val, _is_pk = row
            is_pk_flag = name in pks
            is_autoincrement = is_pk_flag and self._is_autoincrement(table_name, name)
            result.append(
                ColumnInfo(
                    name=name,
                    type=col_type.upper() if col_type else "TEXT",
                    nullable=not notnull and name not in fks,
                    default=default_val,
                    is_primary_key=is_pk_flag,
                    is_autoincrement=is_autoincrement,
                )
            )
        return result

    def get_primary_keys(self, table_name: str) -> list[str]:
        cursor = self.conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
        pks: list[str] = []
        for row in cursor.fetchall():
            _, name, _, _, _, is_pk = row
            if is_pk:
                pks.append(name)
        return pks

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
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
        safe_table = quote_identifier(table_name)
        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {safe_table}")
        return int(cursor.fetchone()[0])

    def get_column_values(self, table_name: str, column_name: str, limit: int = 1000) -> list[Any]:
        safe_table = quote_identifier(table_name)
        safe_column = quote_identifier(column_name)
        cursor = self.conn.execute(
            f"SELECT {safe_column} FROM {safe_table} LIMIT ?",
            [limit],
        )
        return [row[0] for row in cursor.fetchall()]

    def get_index_info(self, table_name: str) -> list[IndexInfo]:
        safe_table = quote_identifier(table_name)
        cursor = self.conn.execute(f"PRAGMA index_list({safe_table})")
        result: list[IndexInfo] = []
        for row in cursor.fetchall():
            idx_name = row[1]
            is_unique = bool(row[2])
            if idx_name.startswith("sqlite_autoindex_"):
                continue
            col_cursor = self.conn.execute(f"PRAGMA index_info({quote_identifier(idx_name)})")
            columns = [cr[2] for cr in col_cursor.fetchall() if cr[2] is not None]
            result.append(IndexInfo(name=idx_name, table=table_name, columns=columns, unique=is_unique))
        return result

    def get_sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        safe_table = quote_identifier(table_name)
        columns = self.get_column_info(table_name)
        col_names = [quote_identifier(c.name) for c in columns]
        cols_sql = ", ".join(col_names)
        cursor = self.conn.execute(f"SELECT {cols_sql} FROM {safe_table} LIMIT ?", [limit])
        col_name_list = [c.name for c in columns]
        return [dict(zip(col_name_list, row, strict=False)) for row in cursor.fetchall()]

    def batch_insert(
        self,
        table_name: str,
        data: Iterator[dict[str, Any]],
        batch_size: int = 5000,
    ) -> int:
        inserted = 0
        batch: list[dict[str, Any]] = []
        for row in data:
            batch.append(row)
            if len(batch) >= batch_size:
                inserted += self._insert_batch(table_name, batch)
                batch = []
        if batch:
            inserted += self._insert_batch(table_name, batch)
        return inserted

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
        safe_table = quote_identifier(table_name)
        self.conn.execute(f"DELETE FROM {safe_table}")
        self.conn.commit()
        logger.debug("Cleared table", table_name=table_name)

    def optimize_for_bulk_write(self, expected_rows: int | None = None) -> None:
        if self._optimizer is not None:
            self._optimizer.preserve()
            self._optimizer.optimize(expected_rows)

    def restore_settings(self) -> None:
        if self._optimizer is not None:
            self._optimizer.restore()
            self.conn.commit()

    def _is_autoincrement(self, table_name: str, column_name: str) -> bool:
        from sqlseed._utils.schema_helpers import detect_autoincrement

        return detect_autoincrement(self.conn.execute, table_name, column_name)

    def _execute_pragma(self, sql: str) -> None:
        self.conn.execute(sql)

    def _fetch_pragma(self, name: str) -> Any:
        cursor = self.conn.execute(f"PRAGMA {name}")
        row = cursor.fetchone()
        return row[0] if row else None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()
