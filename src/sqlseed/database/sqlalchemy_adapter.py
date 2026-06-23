"""Unified database adapter based on SQLAlchemy.

Phase 2 implementation: supports SQLite dialect (via Python built-in sqlite3 driver).
Phase 3 extension: PostgreSQL (via psycopg3 driver, requires sqlseed[postgres]).

Design notes:
- Metadata reading: uses SQLAlchemy inspect() to mask dialect differences
- Bulk write: uses SQLAlchemy bulk_insert_mappings(); PG dialect may use the COPY protocol in the future
- Type normalization: maps database types to sqlseed internal types via TypeNormalizer
- Autoincrement detection: SQLite delegates to schema_helpers; PG uses triple detection via Dialect
- Performance optimization: abstracts dialect-specific optimization strategies via BulkWriteOptimizer

Connection forms:
    "sqlite:///path/to/db"           -> SQLite
    "postgresql://user:pass@host/db" -> PostgreSQL (phase 3)
    "/path/to/db.sqlite"             -> automatically converted to sqlite:/// URL
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import validate_table_name
from sqlseed.database._bulk_optimizer import (
    BulkWriteOptimizer,
    PostgresBulkOptimizer,
    SQLiteBulkOptimizer,
)
from sqlseed.database._dialect import Dialect, PostgresDialect, SQLiteDialect
from sqlseed.database._helpers import apply_bulk_optimize, apply_bulk_restore, batch_insert_rows
from sqlseed.database._protocol import ColumnInfo, ForeignKeyInfo, IndexInfo
from sqlseed.database._type_normalizer import TypeNormalizer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine
    from sqlalchemy.engine.reflection import Inspector
    from typing_extensions import Self

logger = get_logger(__name__)


class SQLAlchemyBatchInserter:
    """Generic batch writer using SQLAlchemy bulk_insert_mappings.

    Applicable to all SQLAlchemy-supported dialects such as SQLite / PostgreSQL / MySQL.
    In the future, PG may be upgraded to the psycopg3 COPY protocol for a 5-10x performance boost.
    """

    def __init__(self, engine: Engine, table_name: str) -> None:
        """Initialize the batch writer.

        Args:
            engine: SQLAlchemy Engine instance.
            table_name: Target table name.
        """
        self._engine = engine
        self._table_name = table_name
        self._normalizer = TypeNormalizer()

    def insert(self, rows: list[dict[str, Any]]) -> int:
        """Insert a batch of row data.

        Reflects the table structure to obtain a Table object, then writes via table.insert().
        Raises RuntimeError when the table does not exist (uniformly caught by the orchestrator).

        Args:
            rows: List of row data, each row is a dict mapping column names to values.

        Returns:
            The actual number of inserted rows; returns 0 when rows is empty.

        Raises:
            RuntimeError: Raised when the target table does not exist.
        """
        if not rows:
            return 0
        from sqlalchemy import MetaData, Table  # noqa: PLC0415
        from sqlalchemy.exc import NoSuchTableError  # noqa: PLC0415

        metadata = MetaData()
        # Reflect the table structure to obtain the Table object
        try:
            table = Table(
                self._table_name,
                metadata,
                autoload_with=self._engine,
                extend_existing=True,
            )
        except NoSuchTableError as e:
            # Convert to RuntimeError so the orchestrator's except clause can uniformly catch it
            raise RuntimeError(f"Table '{self._table_name}' does not exist") from e
        with self._engine.begin() as conn:
            conn.execute(table.insert(), rows)
        return len(rows)


class SQLAlchemyAdapter:
    """Unified database adapter based on SQLAlchemy.

    Masks database differences via SQLAlchemy's dialect system, supporting SQLite (phase 2)
    and PostgreSQL (phase 3).

    Attributes:
        dialect: Database dialect (SQLiteDialect/PostgresDialect)
        bulk_optimizer: Bulk write optimizer (optional)
    """

    def __init__(self) -> None:
        """Initialize the adapter; all internal objects are initially None and require connect() before use."""
        self._engine: Engine | None = None
        self._inspector: Inspector | None = None
        self._dialect: Dialect | None = None
        self._optimizer: BulkWriteOptimizer | None = None
        self._db_url: str = ""
        self._db_path: str = ""
        self._normalizer = TypeNormalizer()

    @property
    def dialect(self) -> Dialect:
        """Database dialect."""
        if self._dialect is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._dialect

    @property
    def bulk_optimizer(self) -> BulkWriteOptimizer | None:
        """Bulk write optimizer (optional)."""
        return self._optimizer

    def connect(self, db_path: str) -> None:
        """Connect to the database.

        Supports two connection forms:
        - Database URL: "sqlite:///path/to/db", "postgresql://user:pass@host/db"
        - Pure file path: "/path/to/db.sqlite" -> automatically converted to sqlite:/// URL

        Args:
            db_path: Database URL or file path

        Raises:
            RuntimeError: When connecting to PG/MySQL but the corresponding driver
                is not installed, gives a friendly hint.
        """
        from sqlalchemy import create_engine, inspect  # noqa: PLC0415
        from sqlalchemy.exc import ArgumentError, NoSuchModuleError  # noqa: PLC0415

        # Pure file path automatically converted to SQLite URL
        if "://" not in db_path:
            self._db_path = db_path
            db_url = f"sqlite:///{db_path}"
        else:
            self._db_path = db_path
            db_url = db_path

        self._db_url = db_url
        try:
            self._engine = create_engine(db_url)
        except NoSuchModuleError as exc:
            # Give a friendly hint when the driver is not installed
            if "postgresql" in db_url:
                raise RuntimeError(
                    "PostgreSQL driver not installed. Install with: pip install sqlseed[postgres]"
                ) from exc
            if "mysql" in db_url:
                raise RuntimeError("MySQL driver not installed. Install with: pip install sqlseed[mysql]") from exc
            raise
        except ArgumentError as exc:
            raise ValueError(f"Invalid database URL: {db_url}") from exc

        self._inspector = inspect(self._engine)
        self._dialect = self._detect_dialect()
        self._optimizer = self._create_optimizer()

        # SQLite needs to enable foreign key constraints
        if self._dialect.name == "sqlite":
            with self._engine.connect() as conn:
                from sqlalchemy import text  # noqa: PLC0415

                conn.execute(text("PRAGMA foreign_keys = ON"))
                conn.commit()

        logger.debug("Connected to database via SQLAlchemy", db_url=db_url, dialect=self._dialect.name)

    def close(self) -> None:
        """Close the database connection and release resources. No-op if not connected."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._inspector = None
            self._dialect = None
            self._optimizer = None
            logger.debug("Closed SQLAlchemy connection", db_url=self._db_url)

    def _detect_dialect(self) -> Dialect:
        """Create the corresponding Dialect implementation based on the engine's dialect name."""
        if self._engine is None:
            raise RuntimeError("Engine not initialized")

        dialect_name = self._engine.dialect.name
        if dialect_name == "sqlite":
            return SQLiteDialect()
        if dialect_name == "postgresql":
            return PostgresDialect()
        if dialect_name == "mysql":
            # Future extension
            raise NotImplementedError("MySQL support not yet implemented")
        raise ValueError(f"Unsupported dialect: {dialect_name}")

    def _create_optimizer(self) -> BulkWriteOptimizer | None:
        """Create the corresponding bulk write optimizer based on the dialect."""
        if self._dialect is None or self._engine is None:
            return None

        if self._dialect.name == "sqlite":
            # SQLite uses PragmaOptimizer, executed via the raw DBAPI connection (supports ? placeholders)
            def execute_fn(sql: str, params: Any = ()) -> Any:
                engine = self._get_engine()
                raw = engine.raw_connection()
                try:
                    cursor = raw.cursor()
                    cursor.execute(sql, params or ())
                    raw.commit()
                    return cursor
                finally:
                    raw.close()

            def fetch_pragma(name: str) -> Any:
                engine = self._get_engine()
                raw = engine.raw_connection()
                try:
                    cursor = raw.cursor()
                    cursor.execute(f"PRAGMA {name}")
                    row = cursor.fetchone()
                    return row[0] if row else None
                finally:
                    raw.close()

            return SQLiteBulkOptimizer(execute_fn=execute_fn, fetch_pragma_fn=fetch_pragma)

        if self._dialect.name == "postgresql":
            # PG uses session-level optimizations such as SET synchronous_commit = OFF
            def pg_execute_fn(sql: str, params: Any = ()) -> Any:
                engine = self._get_engine()
                raw = engine.raw_connection()
                try:
                    cursor = raw.cursor()
                    cursor.execute(sql, params or ())
                    raw.commit()
                    return cursor
                finally:
                    raw.close()

            return PostgresBulkOptimizer(execute_fn=pg_execute_fn)

        # MySQL optimizer left for future work
        return None

    def _get_engine(self) -> Engine:
        """Get the current Engine instance.

        Raises:
            RuntimeError: Raised when accessed without calling connect() first.
        """
        if self._engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._engine

    def _get_inspector(self) -> Inspector:
        """Get the current Inspector instance.

        Raises:
            RuntimeError: Raised when accessed without calling connect() first.
        """
        if self._inspector is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._inspector

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        """Execute a SQL statement.

        Uses a raw DBAPI connection to support native placeholders (SQLite: ?, PG: %s) and tuple parameters,
        keeping protocol semantics consistent with RawSQLiteAdapter.
        """
        engine = self._get_engine()
        raw = engine.raw_connection()
        try:
            cursor = raw.cursor()
            cursor.execute(sql, params)
            raw.commit()
            return cursor
        finally:
            raw.close()

    def get_table_names(self) -> list[str]:
        """Return all user table names in the database."""
        inspector = self._get_inspector()
        return inspector.get_table_names()

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        """Get column information for a table.

        Reads column definitions via the SQLAlchemy Inspector, and constructs a ColumnInfo list
        combined with the primary key set and autoincrement detection.
        Returns an empty list when the table does not exist (consistent with RawSQLiteAdapter).

        Args:
            table_name: Target table name.

        Returns:
            A list of ColumnInfo for all columns of the table; returns an empty list when the table does not exist.
        """
        validate_table_name(table_name)
        from sqlalchemy.exc import NoSuchTableError  # noqa: PLC0415

        inspector = self._get_inspector()
        dialect = self.dialect

        try:
            pks = set(inspector.get_pk_constraint(table_name).get("constrained_columns", []))
            columns = inspector.get_columns(table_name)
        except NoSuchTableError:
            # Consistent with RawSQLiteAdapter: a non-existent table returns an empty list
            return []

        result: list[ColumnInfo] = []
        for col in columns:
            raw_type = str(col.get("type", ""))
            normalized = self._normalizer.normalize(raw_type, dialect.name)
            is_pk = col["name"] in pks
            is_autoincrement = is_pk and self._detect_autoincrement(table_name, dict(col))

            result.append(
                ColumnInfo(
                    name=col["name"],
                    type=normalized.display,
                    nullable=col.get("nullable", True) and not is_pk,
                    default=col.get("default"),
                    is_primary_key=is_pk,
                    is_autoincrement=is_autoincrement,
                )
            )
        return result

    def _detect_autoincrement(self, table_name: str, column_info: dict[str, Any]) -> bool:
        """Detect whether a column is autoincrement.

        SQLite: parses the CREATE TABLE SQL via schema_helpers.detect_autoincrement
                (SQLiteDialect.detect_autoincrement is a placeholder implementation).
        PG: triple detection via PostgresDialect.detect_autoincrement
             (identity / nextval / autoincrement flag).
        """
        dialect = self.dialect

        if dialect.name == "sqlite":
            from sqlseed._utils.schema_helpers import detect_autoincrement  # noqa: PLC0415

            engine = self._get_engine()
            raw = engine.raw_connection()
            try:
                cursor = raw.cursor()

                def execute_fn(sql: str, params: Any = ()) -> Any:
                    cursor.execute(sql, params or ())
                    return cursor

                return detect_autoincrement(execute_fn, table_name, column_info["name"])
            finally:
                raw.close()

        # PG / other dialects: delegate to Dialect.detect_autoincrement
        return dialect.detect_autoincrement(column_info)

    def get_primary_keys(self, table_name: str) -> list[str]:
        """Get the list of primary key column names for a table.

        Args:
            table_name: Target table name.

        Returns:
            List of primary key column names; returns an empty list when the table does not exist.
        """
        validate_table_name(table_name)
        from sqlalchemy.exc import NoSuchTableError  # noqa: PLC0415

        inspector = self._get_inspector()
        try:
            return list(inspector.get_pk_constraint(table_name).get("constrained_columns", []))
        except NoSuchTableError:
            return []

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        """Get foreign key information for a table.

        Args:
            table_name: Target table name.

        Returns:
            A list of ForeignKeyInfo for all foreign keys of the table;
            returns an empty list when the table does not exist.
        """
        validate_table_name(table_name)
        from sqlalchemy.exc import NoSuchTableError  # noqa: PLC0415

        inspector = self._get_inspector()
        try:
            fks = inspector.get_foreign_keys(table_name)
        except NoSuchTableError:
            return []
        result: list[ForeignKeyInfo] = []
        for fk in fks:
            referred_table = fk.get("referred_table", "")
            constrained_cols = fk.get("constrained_columns", [])
            referred_cols = fk.get("referred_columns", [])
            for i, from_col in enumerate(constrained_cols):
                to_col = referred_cols[i] if i < len(referred_cols) else ""
                result.append(
                    ForeignKeyInfo(
                        column=from_col,
                        ref_table=referred_table,
                        ref_column=to_col,
                    )
                )
        return result

    def get_row_count(self, table_name: str) -> int:
        """Get the total number of rows in a table.

        Args:
            table_name: Target table name.

        Returns:
            The number of rows in the table; returns 0 when the table does not exist (consistent with RawSQLiteAdapter).
        """
        validate_table_name(table_name)
        from sqlalchemy import text  # noqa: PLC0415

        # Return 0 when the table does not exist (consistent with RawSQLiteAdapter)
        inspector = self._get_inspector()
        if not inspector.has_table(table_name):
            return 0
        safe_table = self.dialect.quote_identifier(table_name)
        engine = self._get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {safe_table}"))
            row = result.fetchone()
            return int(row[0]) if row else 0

    def get_column_values(self, table_name: str, column_name: str, limit: int = 1000) -> list[Any]:
        """Get all values of a specified column.

        Args:
            table_name: Target table name.
            column_name: Target column name.
            limit: Maximum number of rows to return, default 1000.

        Returns:
            A list of values for that column; returns an empty list when the table does not exist.
        """
        validate_table_name(table_name)
        from sqlalchemy import text  # noqa: PLC0415

        # Return an empty list when the table does not exist
        inspector = self._get_inspector()
        if not inspector.has_table(table_name):
            return []
        dialect = self.dialect
        safe_table = dialect.quote_identifier(table_name)
        safe_column = dialect.quote_identifier(column_name)
        sql = f"SELECT {safe_column} FROM {safe_table} LIMIT :limit"
        engine = self._get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(sql), {"limit": limit})
            return [row[0] for row in result.fetchall()]

    def get_index_info(self, table_name: str) -> list[IndexInfo]:
        """Get index information for a table.

        Args:
            table_name: Target table name.

        Returns:
            A list of IndexInfo for all indexes of the table; returns an empty list when the table does not exist.
        """
        validate_table_name(table_name)
        from sqlalchemy.exc import NoSuchTableError  # noqa: PLC0415

        inspector = self._get_inspector()
        try:
            indexes = inspector.get_indexes(table_name)
        except NoSuchTableError:
            return []
        result: list[IndexInfo] = []
        for idx in indexes:
            idx_name = idx.get("name") or ""
            col_names = [c or "" for c in idx.get("column_names", [])]
            result.append(
                IndexInfo(
                    name=idx_name,
                    table=table_name,
                    columns=tuple(col_names),
                    unique=bool(idx.get("unique", False)),
                )
            )
        return result

    def get_sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Get sample rows from a table.

        Args:
            table_name: Target table name.
            limit: Maximum number of rows to return, default 5.

        Returns:
            A list of dicts keyed by column names with row values; returns an empty
            list when the table does not exist or has no columns.
        """
        validate_table_name(table_name)
        from sqlalchemy import text  # noqa: PLC0415

        dialect = self.dialect
        columns = self.get_column_info(table_name)
        # Return an empty list when the table does not exist or has no columns (consistent with RawSQLiteAdapter)
        if not columns:
            return []
        col_names = [dialect.quote_identifier(c.name) for c in columns]
        safe_table = dialect.quote_identifier(table_name)
        cols_sql = ", ".join(col_names)
        sql = f"SELECT {cols_sql} FROM {safe_table} LIMIT :limit"

        engine = self._get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(sql), {"limit": limit})
            col_name_list = [c.name for c in columns]
            return [dict(zip(col_name_list, row, strict=True)) for row in result.fetchall()]

    def batch_insert(
        self,
        table_name: str,
        data: Iterator[dict[str, Any]],
        batch_size: int = 5000,
    ) -> int:
        """Insert data in batches.

        Args:
            table_name: Target table name.
            data: Row data iterator, each row is a dict mapping column names to values.
            batch_size: Maximum number of rows per batch, default 5000.

        Returns:
            Total number of inserted rows.
        """
        validate_table_name(table_name)
        engine = self._get_engine()
        inserter = SQLAlchemyBatchInserter(engine, table_name)
        return batch_insert_rows(data, batch_size, inserter.insert)

    def clear_table(self, table_name: str) -> None:
        """Clear table data and reset the autoincrement counter.

        Args:
            table_name: Target table name.
        """
        validate_table_name(table_name)

        dialect = self.dialect
        safe_table = dialect.quote_identifier(table_name)
        engine = self._get_engine()
        raw = engine.raw_connection()
        try:
            cursor = raw.cursor()
            cursor.execute(f"DELETE FROM {safe_table}")
            # Reset the autoincrement counter
            with contextlib.suppress(Exception):
                dialect.reset_autoincrement(
                    lambda sql, params=None: cursor.execute(sql, params or ()),
                    table_name,
                )
            raw.commit()
        finally:
            raw.close()
        logger.debug("Cleared table", table_name=table_name)

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


__all__ = ["SQLAlchemyAdapter", "SQLAlchemyBatchInserter"]
