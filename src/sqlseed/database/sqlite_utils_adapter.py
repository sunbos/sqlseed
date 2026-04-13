from __future__ import annotations

from typing import TYPE_CHECKING, Any

from typing_extensions import Self

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.database._protocol import ColumnInfo, ForeignKeyInfo, IndexInfo
from sqlseed.database.optimizer import PragmaOptimizer

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = get_logger(__name__)


class SQLiteUtilsAdapter:
    def __init__(self) -> None:
        self._db: Any = None
        self._optimizer: PragmaOptimizer | None = None
        self._db_path: str = ""

    def connect(self, db_path: str) -> None:
        import sqlite_utils

        self._db_path = db_path
        self._db = sqlite_utils.Database(db_path)
        self._optimizer = PragmaOptimizer(
            execute_fn=self._execute_pragma,
            fetch_pragma_fn=self._fetch_pragma,
        )
        logger.debug("Connected to database via sqlite-utils", db_path=db_path)

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
            logger.debug("Closed sqlite-utils connection", db_path=self._db_path)

    def get_table_names(self) -> list[str]:
        return list(self._db.table_names())

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        table = self._db[table_name]
        pks = self.get_primary_keys(table_name)
        fks = {fk.column for fk in self.get_foreign_keys(table_name)}

        result: list[ColumnInfo] = []
        for col in table.columns:
            col_name = col.name
            is_pk = col_name in pks
            is_autoincrement = is_pk and self._is_autoincrement(table_name, col_name)
            nullable = not is_pk and col_name not in fks and not col.notnull

            default = col.default_value

            result.append(
                ColumnInfo(
                    name=col_name,
                    type=col.type if isinstance(col.type, str) else str(col.type),
                    nullable=nullable,
                    default=default,
                    is_primary_key=is_pk,
                    is_autoincrement=is_autoincrement,
                )
            )
        return result

    def get_primary_keys(self, table_name: str) -> list[str]:
        try:
            table = self._db[table_name]
            pks = table.pks
            return pks if pks else []
        except Exception:
            logger.debug("Failed to get primary keys", table=table_name)
            return []

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        try:
            table = self._db[table_name]
            fks = table.foreign_keys
            return [
                ForeignKeyInfo(
                    column=fk.column,
                    ref_table=fk.other_table,
                    ref_column=fk.other_column,
                )
                for fk in fks
            ]
        except Exception:
            logger.debug("Failed to get foreign keys", table=table_name)
            return []

    def get_row_count(self, table_name: str) -> int:
        return int(self._db[table_name].count)

    def get_column_values(self, table_name: str, column_name: str, limit: int = 1000) -> list[Any]:
        safe_table = quote_identifier(table_name)
        safe_column = quote_identifier(column_name)
        sql = f"SELECT {safe_column} FROM {safe_table} LIMIT ?"
        rows = self._db.execute(sql, [limit]).fetchall()
        return [row[0] for row in rows]

    def get_index_info(self, table_name: str) -> list[IndexInfo]:
        safe_table = quote_identifier(table_name)
        rows = self._db.execute(f"PRAGMA index_list({safe_table})").fetchall()
        result: list[IndexInfo] = []
        for row in rows:
            idx_name = row[1]
            is_unique = bool(row[2])
            if idx_name.startswith("sqlite_autoindex_"):
                continue
            col_rows = self._db.execute(f"PRAGMA index_info({quote_identifier(idx_name)})").fetchall()
            columns = [cr[2] for cr in col_rows if cr[2] is not None]
            result.append(IndexInfo(name=idx_name, table=table_name, columns=columns, unique=is_unique))
        return result

    def get_sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        safe_table = quote_identifier(table_name)
        columns = self.get_column_info(table_name)
        col_names = [quote_identifier(c.name) for c in columns]
        cols_sql = ", ".join(col_names)
        sql = f"SELECT {cols_sql} FROM {safe_table} LIMIT ?"
        rows = self._db.execute(sql, [limit]).fetchall()
        col_name_list = [c.name for c in columns]
        return [dict(zip(col_name_list, row)) for row in rows]

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
                self._db[table_name].insert_all(batch)
                inserted += len(batch)
                batch = []
        if batch:
            self._db[table_name].insert_all(batch)
            inserted += len(batch)
        return inserted

    def clear_table(self, table_name: str) -> None:
        safe_table = quote_identifier(table_name)
        self._db.execute(f"DELETE FROM {safe_table}")
        logger.debug("Cleared table", table_name=table_name)

    def optimize_for_bulk_write(self, expected_rows: int | None = None) -> None:
        if self._optimizer is not None:
            self._optimizer.preserve()
            self._optimizer.optimize(expected_rows)

    def restore_settings(self) -> None:
        if self._optimizer is not None:
            self._optimizer.restore()

    def _is_autoincrement(self, table_name: str, column_name: str) -> bool:
        from sqlseed._utils.schema_helpers import detect_autoincrement

        return detect_autoincrement(self._db.execute, table_name, column_name)

    def _execute_pragma(self, sql: str) -> None:
        self._db.execute(sql)

    def _fetch_pragma(self, name: str) -> Any:
        result = self._db.execute(f"PRAGMA {name}").fetchone()
        return result[0] if result else None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()
