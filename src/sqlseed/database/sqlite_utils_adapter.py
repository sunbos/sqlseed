from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import quote_identifier, validate_table_name
from sqlseed.database._base_adapter import BaseSQLiteAdapter
from sqlseed.database._compat import HAS_SQLITE_UTILS, sqlite_utils
from sqlseed.database._helpers import batch_insert_rows
from sqlseed.database._protocol import ColumnInfo, ForeignKeyInfo
from sqlseed.database.optimizer import PragmaOptimizer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = get_logger(__name__)


class SQLiteUtilsAdapter(BaseSQLiteAdapter):
    def __init__(self) -> None:
        super().__init__()
        self._db: Any = None

    def _get_execute_fn(self) -> Callable[..., Any]:
        return self._db.execute  # type: ignore[no-any-return]

    def connect(self, db_path: str) -> None:
        if not HAS_SQLITE_UTILS:
            raise RuntimeError("sqlite-utils is not available")

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
        validate_table_name(table_name)
        table = self._db[table_name]
        pks = self.get_primary_keys(table_name)

        result: list[ColumnInfo] = []
        for col in table.columns:
            col_name = col.name
            is_pk = col_name in pks
            is_autoincrement = is_pk and self._is_autoincrement(table_name, col_name)
            nullable = not is_pk and not col.notnull

            default = col.default_value
            if default == "NULL":
                default = None

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
        validate_table_name(table_name)
        try:
            table = self._db[table_name]
            pks = table.pks
            return pks if pks else []
        except (ValueError, KeyError, AttributeError):
            logger.debug("Failed to get primary keys", table=table_name)
            return []

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        validate_table_name(table_name)
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
        except (ValueError, KeyError, AttributeError):
            logger.debug("Failed to get foreign keys", table=table_name)
            return []

    def get_row_count(self, table_name: str) -> int:
        validate_table_name(table_name)
        return int(self._db[table_name].count)

    def batch_insert(
        self,
        table_name: str,
        data: Iterator[dict[str, Any]],
        batch_size: int = 5000,
    ) -> int:
        validate_table_name(table_name)
        return batch_insert_rows(
            (item or {} for item in data),
            batch_size,
            lambda b: self._insert_batch(table_name, b),
        )

    def _insert_batch(self, table_name: str, batch: list[dict[str, Any]]) -> int:
        if not batch:
            return 0
        if batch[0]:
            self._db[table_name].insert_all(batch)
            return len(batch)
        safe_table = quote_identifier(table_name)
        conn = self._db.conn
        for _ in batch:
            conn.execute(f"INSERT INTO {safe_table} DEFAULT VALUES")
        conn.commit()
        return len(batch)

    def clear_table(self, table_name: str) -> None:
        validate_table_name(table_name)
        safe_table = quote_identifier(table_name)
        self._db.execute(f"DELETE FROM {safe_table}")
        logger.debug("Cleared table", table_name=table_name)

    def _execute_pragma(self, sql: str) -> None:
        self._db.execute(sql)

    def _fetch_pragma(self, name: str) -> Any:
        result = self._db.execute(f"PRAGMA {name}").fetchone()
        return result[0] if result else None
