"""Unified database adapter based on SQLAlchemy.

Phase 2 implementation: supports SQLite dialect (via Python built-in sqlite3 driver).
Phase 3 extension: PostgreSQL (via psycopg3 driver, requires sqlseed[postgres]).

Design notes:
- Metadata reading: uses SQLAlchemy inspect() to mask dialect differences
- Bulk write: uses SQLAlchemy bulk_insert_mappings(); PG dialect may use the COPY protocol in the future
- Type normalization: maps database types to sqlseed internal types via TypeNormalizer
- Autoincrement detection: delegated to the Dialect (SQLite parses sqlite_master; PG uses column_info)
- Performance optimization: abstracts dialect-specific optimization strategies via BulkWriteOptimizer

Connection forms:
    "sqlite:///path/to/db"           -> SQLite
    "postgresql://user:pass@host/db" -> PostgreSQL (phase 3)
    "/path/to/db.sqlite"             -> automatically converted to sqlite:/// URL
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import MetaData, Table, create_engine, event, inspect, text
from sqlalchemy.exc import ArgumentError, NoSuchModuleError, NoSuchTableError, SQLAlchemyError

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import validate_table_name
from sqlseed.database._bulk_optimizer import (
    BulkWriteOptimizer,
    PostgresBulkOptimizer,
    SQLiteBulkOptimizer,
)
from sqlseed.database._dialect import Dialect, PostgresDialect, SQLiteDialect
from sqlseed.database._helpers import apply_bulk_optimize, apply_bulk_restore, batch_insert_rows
from sqlseed.database._protocol import CheckConstraintInfo, ColumnInfo, ForeignKeyInfo, IndexInfo
from sqlseed.database._type_normalizer import TypeNormalizer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine
    from sqlalchemy.engine.reflection import Inspector
    from typing_extensions import Self

logger = get_logger(__name__)


class SQLAlchemyBatchInserter:
    """Generic batch writer using SQLAlchemy bulk_insert_mappings.

    Applicable to all SQLAlchemy-supported dialects such as SQLite / PostgreSQL.
    In the future, PG may be upgraded to the psycopg3 COPY protocol for a 5-10x performance boost.

    H2 optimization: supports a pre-reflected Table object passed in via the constructor
    to avoid reflecting the table structure on every batch, and accepts a shared Connection
    in insert() so all batches can be written within a single outer transaction.
    """

    def __init__(self, engine: Engine, table_name: str, table: Any = None) -> None:
        """Initialize the batch writer.

        Args:
            engine: SQLAlchemy Engine instance.
            table_name: Target table name.
            table: Optional pre-reflected SQLAlchemy Table object (H2 optimization).
                When provided, reuses it instead of reflecting on every insert.
        """
        self._engine = engine
        self._table_name = table_name
        self._table = table  # cached Table object (H2 optimization)
        self._normalizer = TypeNormalizer()

    def _resolve_table(self) -> Any:
        """Return the cached Table or reflect it on first use.

        Raises:
            RuntimeError: Raised when the target table does not exist.
        """
        if self._table is not None:
            return self._table

        metadata = MetaData()
        try:
            self._table = Table(
                self._table_name,
                metadata,
                autoload_with=self._engine,
                extend_existing=True,
            )
        except NoSuchTableError as e:
            raise RuntimeError(f"Table '{self._table_name}' does not exist") from e
        return self._table

    def insert(self, rows: list[dict[str, Any]], conn: Any = None) -> int:
        """Insert a batch of row data.

        When a pre-reflected Table is supplied, reuses it instead of reflecting on every call.
        When a shared Connection is supplied, writes within that transaction; otherwise opens a new one.

        Args:
            rows: List of row data, each row is a dict mapping column names to values.
            conn: Optional shared SQLAlchemy Connection for single-transaction batching.

        Returns:
            The actual number of inserted rows; returns 0 when rows is empty.

        Raises:
            RuntimeError: Raised when the target table does not exist.
        """
        if not rows:
            return 0
        table = self._resolve_table()
        if conn is not None:
            conn.execute(table.insert(), rows)
        else:
            with self._engine.begin() as connection:
                connection.execute(table.insert(), rows)
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
        self._table_cache: dict[str, Any] = {}

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
            RuntimeError: When connecting to PG but the corresponding driver
                is not installed, gives a friendly hint.
            ValueError: When the database URL is invalid (sqlalchemy.ArgumentError).
        """
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
            raise
        except ArgumentError as exc:
            raise ValueError(f"Invalid database URL: {db_url}") from exc

        self._inspector = inspect(self._engine)
        self._dialect = self._detect_dialect()
        self._optimizer = self._create_optimizer()

        # SQLite needs to enable foreign key constraints on every new connection,
        # because PRAGMA foreign_keys is per-connection (not persisted to disk).
        # Using an event listener ensures all connections created by this engine
        # (including from the connection pool) have FK enforcement enabled.
        if self._dialect.name == "sqlite":

            @event.listens_for(self._engine, "connect")
            def _enable_sqlite_fk(dbapi_conn: Any, _record: Any) -> None:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.close()

        logger.debug("Connected to database via SQLAlchemy", db_url=db_url, dialect=self._dialect.name)

    def close(self) -> None:
        """Close the database connection and release resources. No-op if not connected."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._inspector = None
            self._dialect = None
            self._optimizer = None
            self._table_cache.clear()
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
        raise ValueError(f"Unsupported dialect: {dialect_name}")

    def _create_optimizer(self) -> BulkWriteOptimizer | None:
        """Create the corresponding bulk write optimizer based on the dialect."""
        if self._dialect is None or self._engine is None:
            return None

        # Shared execute_fn: dialect-agnostic raw DBAPI execution with commit.
        # Used by both SQLiteBulkOptimizer (for PRAGMA setup) and
        # PostgresBulkOptimizer (for SET synchronous_commit = OFF, etc.).
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

        if self._dialect.name == "sqlite":
            # SQLite additionally needs a fetch_pragma helper for PRAGMA queries.
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
            return PostgresBulkOptimizer(execute_fn=execute_fn)

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
        """Execute a SQL statement and return the cursor.

        Uses a raw DBAPI connection to support native placeholders (SQLite: ?, PG: %s) and tuple parameters,
        keeping protocol semantics consistent with RawSQLiteAdapter.

        The returned cursor holds a reference to the underlying DBAPI
        connection. Callers MUST invoke ``cursor.close()`` after fetching
        results (``fetchone``/``fetchall``) so the connection is returned
        to the pool promptly. Previously this method closed ``raw`` in a
        ``finally`` block, which left the cursor pointing at a
        already-released connection — on SQLite the cached result set
        masked the bug, but on PostgreSQL (psycopg3) ``fetchone``/
        ``fetchall`` raised ``OperationalError: cursor already closed``.

        If the caller forgets ``cursor.close()``, the connection is still
        reclaimed when the cursor is garbage-collected (via the DBAPI
        connection's ``__del__``), so there is no hard leak — only delayed
        return to the pool.
        """
        engine = self._get_engine()
        raw = engine.raw_connection()
        try:
            cursor = raw.cursor()
            try:
                cursor.execute(sql, params)
                raw.commit()
                return cursor
            except Exception:
                cursor.close()
                raise
        except Exception:
            raw.close()
            raise

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
            col_dict = dict(col)
            is_pk = col["name"] in pks
            is_autoincrement = is_pk and self._detect_autoincrement(table_name, col_dict)
            is_computed = col_dict.get("computed") is not None

            default_val = col_dict.get("default")
            if default_val is None and col_dict.get("server_default") is not None:
                default_val = str(col_dict["server_default"])

            result.append(
                ColumnInfo(
                    name=col["name"],
                    type=normalized.display,
                    nullable=col.get("nullable", True) and not is_pk,
                    default=default_val,
                    is_primary_key=is_pk,
                    is_autoincrement=is_autoincrement,
                    is_computed=is_computed,
                )
            )
        return result

    def _detect_autoincrement(self, table_name: str, column_info: dict[str, Any]) -> bool:
        """Detect whether a column is autoincrement.

        Pure delegation to the Dialect's detect_autoincrement with a
        raw-connection execute_fn. SQLite uses it to query sqlite_master;
        PG ignores it and detects from column_info alone. No dialect
        branching — adding a new dialect requires no change here.
        """
        dialect = self.dialect
        engine = self._get_engine()
        raw = engine.raw_connection()
        cursor = raw.cursor()
        try:

            def execute_fn(sql: str, params: Any = ()) -> Any:
                cursor.execute(sql, params or ())
                return cursor

            return dialect.detect_autoincrement(
                column_info,
                table_name=table_name,
                execute_fn=execute_fn,
            )
        finally:
            cursor.close()
            raw.close()

    def get_primary_keys(self, table_name: str) -> list[str]:
        """Get the list of primary key column names for a table.

        Args:
            table_name: Target table name.

        Returns:
            List of primary key column names; returns an empty list when the table does not exist.
        """
        validate_table_name(table_name)

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

    def get_check_constraints(self, table_name: str) -> list[CheckConstraintInfo]:
        """Get CHECK constraint metadata for a table.

        Uses SQLAlchemy's inspector to reflect CHECK constraints. The raw SQL
        expression is returned verbatim so the AI plugin can convey business
        rules to the LLM. Column references are extracted via a simple
        identifier scan (lowercased, SQL keywords filtered out); when parsing
        fails, an empty tuple is returned and the LLM still sees ``expression``.

        Args:
            table_name: Target table name.

        Returns:
            A list of CheckConstraintInfo for all CHECK constraints on the
            table; returns an empty list when the table does not exist or the
            backend does not expose CHECK constraints.
        """
        validate_table_name(table_name)

        inspector = self._get_inspector()
        try:
            checks = inspector.get_check_constraints(table_name)
        except NoSuchTableError:
            return []
        except (SQLAlchemyError, NotImplementedError) as exc:
            # Backend may not support CHECK reflection (e.g. older SQLAlchemy
            # versions or dialects without get_check_constraints). Narrow to
            # SQLAlchemyError + NotImplementedError so genuine bugs (e.g.
            # AttributeError from a typo) are not silently swallowed.
            logger.debug("CHECK constraint reflection unavailable", table_name=table_name, error=str(exc))
            return []

        # SQL keywords to exclude when extracting column identifiers.
        sql_keywords = frozenset(
            {
                "in",
                "and",
                "or",
                "not",
                "null",
                "is",
                "between",
                "like",
                "case",
                "when",
                "then",
                "else",
                "end",
                "true",
                "false",
                "length",
                "round",
                "abs",
                "coalesce",
                "if",
                "exists",
            }
        )
        result: list[CheckConstraintInfo] = []
        for chk in checks:
            name = chk.get("name") or ""
            expression = chk.get("sqltext") or ""
            # Extract candidate identifiers and filter against keywords.
            identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)
            cols = tuple(i for i in identifiers if i.lower() not in sql_keywords)
            result.append(
                CheckConstraintInfo(
                    name=name,
                    table=table_name,
                    columns=cols,
                    expression=expression,
                )
            )
        return result

    def get_sample_rows(
        self,
        table_name: str,
        limit: int = 5,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get sample rows from a table.

        Args:
            table_name: Target table name.
            limit: Maximum number of rows to return, default 5.
            columns: Optional list of column names to project. When ``None``,
                all columns are selected. When provided, only the named columns
                are fetched (reduces data transfer for wide tables with many
                columns but only a few PK/FK columns of interest). Unknown
                names are ignored.

        Returns:
            A list of dicts keyed by column names with row values; returns an empty
            list when the table does not exist or has no columns.
        """
        validate_table_name(table_name)

        dialect = self.dialect
        all_columns = self.get_column_info(table_name)
        # Return an empty list when the table does not exist or has no columns (consistent with RawSQLiteAdapter)
        if not all_columns:
            return []
        if columns is not None:
            projection_set = set(columns)
            selected = [c for c in all_columns if c.name in projection_set]
            if not selected:
                return []
        else:
            selected = all_columns
        col_names = [dialect.quote_identifier(c.name) for c in selected]
        safe_table = dialect.quote_identifier(table_name)
        cols_sql = ", ".join(col_names)
        sql = f"SELECT {cols_sql} FROM {safe_table} LIMIT :limit"

        engine = self._get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(sql), {"limit": limit})
            col_name_list = [c.name for c in selected]
            return [dict(zip(col_name_list, row, strict=True)) for row in result.fetchall()]

    def _get_table(self, table_name: str) -> Any:
        """Get a cached SQLAlchemy Table object, reflecting on first access (H2 optimization).

        Args:
            table_name: Target table name.

        Returns:
            SQLAlchemy Table object.

        Raises:
            RuntimeError: Raised when the target table does not exist.
        """
        if table_name in self._table_cache:
            return self._table_cache[table_name]

        engine = self._get_engine()
        metadata = MetaData()
        try:
            table = Table(table_name, metadata, autoload_with=engine, extend_existing=True)
        except NoSuchTableError as e:
            raise RuntimeError(f"Table '{table_name}' does not exist") from e
        self._table_cache[table_name] = table
        return table

    def batch_insert(
        self,
        table_name: str,
        data: Iterator[dict[str, Any]],
        batch_size: int = 5000,
    ) -> int:
        """Insert data in batches.

        Uses a cached Table object (H2 optimization: reflect once, reuse for all batches)
        and wraps all batches in a single outer transaction via ``engine.begin()``.

        Atomicity semantics (behavioral change from pre-H2):
            All batches commit or roll back together. If batch K fails, batches 1..K-1
            are rolled back and 0 rows are persisted. This is preferable for test-data
            generation (avoids partial datasets that violate FK constraints), but
            differs from the previous per-batch commit semantics where a failure at
            batch 8/10 would leave the first 7 batches committed.

        Args:
            table_name: Target table name.
            data: Row data iterator, each row is a dict mapping column names to values.
            batch_size: Maximum number of rows per batch, default 5000.

        Returns:
            Total number of inserted rows.
        """
        validate_table_name(table_name)
        engine = self._get_engine()
        table = self._get_table(table_name)
        inserter = SQLAlchemyBatchInserter(engine, table_name, table=table)
        with engine.begin() as conn:
            return batch_insert_rows(data, batch_size, lambda batch: inserter.insert(batch, conn=conn))

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
        cursor = raw.cursor()
        try:
            cursor.execute(f"DELETE FROM {safe_table}")
            # Reset the autoincrement counter. Each Dialect self-handles expected
            # failures (SQLite: sqlite_sequence missing; PG: no sequence) via its
            # own reset_autoincrement implementation, so no dialect-specific
            # exception handling is needed here.
            dialect.reset_autoincrement(
                lambda sql, params=None: cursor.execute(sql, params or ()),
                table_name,
            )
            raw.commit()
        finally:
            cursor.close()
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
