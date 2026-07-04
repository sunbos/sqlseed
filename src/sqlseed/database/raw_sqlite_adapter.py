"""Database adapter based on the native sqlite3 module (used only for zero-dependency tests)."""

from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import build_insert_sql, quote_identifier, validate_table_name
from sqlseed.database._base_adapter import BaseRawSQLiteAdapter
from sqlseed.database._helpers import batch_insert_rows
from sqlseed.database._protocol import CheckConstraintInfo, ColumnInfo, ForeignKeyInfo
from sqlseed.database.optimizer import PragmaOptimizer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = get_logger(__name__)


class RawSQLiteAdapter(BaseRawSQLiteAdapter):
    """Database adapter based on the Python built-in sqlite3 module.

    Used only for zero-dependency test scenarios, without relying on SQLAlchemy.
    For production, use SQLAlchemyAdapter to get multi-dialect support.

    Implements SQLite bulk write optimization (PRAGMA tuning) via PragmaOptimizer.
    """

    def __init__(self) -> None:
        """Initialize the adapter; the connection object is initially None."""
        super().__init__()
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Current sqlite3 connection object.

        Raises:
            RuntimeError: Raised when accessed without calling connect() first.
        """
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def _get_execute_fn(self) -> Callable[..., Any]:
        """Return conn.execute as the SQL execution function."""
        return self.conn.execute

    def connect(self, db_path: str) -> None:
        """Connect to a SQLite database file.

        After connecting, foreign key constraints are automatically enabled
        and a PragmaOptimizer instance is created.

        Args:
            db_path: SQLite database file path.
        """
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._optimizer = PragmaOptimizer(
            execute_fn=self._execute_pragma,
            fetch_pragma_fn=self._fetch_pragma,
        )
        logger.debug("Connected to database via raw sqlite3", db_path=db_path)

    def close(self) -> None:
        """Close the database connection. No-op if not connected."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.debug("Closed raw sqlite3 connection", db_path=self._db_path)

    def get_table_names(self) -> list[str]:
        """Return all user table names in the database (excluding internal tables with the sqlite_ prefix)."""
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        return [row[0] for row in cursor.fetchall()]

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        """Get column information for a table.

        Reads column definitions via PRAGMA table_info, and constructs a ColumnInfo list
        combined with the primary key set and autoincrement detection.

        Args:
            table_name: Target table name.

        Returns:
            A list of ColumnInfo for all columns of the table.
        """
        validate_table_name(table_name)
        pks = set(self.get_primary_keys(table_name))

        cursor = self.conn.execute(f"PRAGMA table_xinfo({quote_identifier(table_name)})")
        result: list[ColumnInfo] = []
        for row in cursor.fetchall():
            _, name, col_type, notnull, default_val, _, hidden = row
            if default_val == "NULL":
                default_val = None
            is_pk_flag = name in pks
            is_autoincrement = is_pk_flag and self._is_autoincrement(table_name, name)
            is_computed = hidden in (2, 3)
            result.append(
                ColumnInfo(
                    name=name,
                    type=col_type.upper() if col_type else "TEXT",
                    nullable=not is_pk_flag and not notnull,
                    default=default_val,
                    is_primary_key=is_pk_flag,
                    is_autoincrement=is_autoincrement,
                    is_computed=is_computed,
                )
            )
        return result

    def get_primary_keys(self, table_name: str) -> list[str]:
        """Get the list of primary key column names for a table.

        Args:
            table_name: Target table name.

        Returns:
            List of primary key column names, in the order returned by PRAGMA table_info.
        """
        validate_table_name(table_name)
        cursor = self.conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
        pks: list[str] = []
        for row in cursor.fetchall():
            _, name, _, _, _, is_pk = row
            if is_pk:
                pks.append(name)
        return pks

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        """Get foreign key information for a table.

        Args:
            table_name: Target table name.

        Returns:
            A list of ForeignKeyInfo for all foreign keys of the table.
        """
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
        """Get the total number of rows in a table.

        Args:
            table_name: Target table name.

        Returns:
            The number of rows in the table.
        """
        validate_table_name(table_name)
        safe_table = quote_identifier(table_name)
        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {safe_table}")
        return int(cursor.fetchone()[0])

    def get_check_constraints(self, table_name: str) -> list[CheckConstraintInfo]:
        """Get CHECK constraint metadata for a table by parsing sqlite_master.sql.

        SQLite's built-in reflection (``PRAGMA table_info``) does not expose
        CHECK constraints, so this implementation parses the ``CREATE TABLE``
        SQL stored in ``sqlite_master.sql``. Constraints are extracted by
        locating top-level ``CHECK (...)`` clauses (parenthesis-aware).

        Args:
            table_name: Target table name.

        Returns:
            A list of CheckConstraintInfo with the raw CHECK expression and
            best-effort column references; returns an empty list when the
            table has no CHECK constraints or cannot be reflected.
        """
        validate_table_name(table_name)
        cursor = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            [table_name],
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return []
        create_sql = row[0]

        # Parenthesis-aware scan for "CHECK (" at the top level of the CREATE
        # TABLE body. Handles nested parens (e.g., CHECK(length(phone) >= 10)).
        results: list[CheckConstraintInfo] = []
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
        for match in re.finditer(r"CHECK\s*\(", create_sql, re.IGNORECASE):
            # Walk from the opening paren to its matching close.
            start = match.end() - 1
            depth = 0
            end = -1
            for i in range(start, len(create_sql)):
                ch = create_sql[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end == -1:
                continue
            expression = create_sql[start + 1 : end].strip()
            identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)
            cols = tuple(i for i in identifiers if i.lower() not in sql_keywords)
            results.append(
                CheckConstraintInfo(
                    name="",
                    table=table_name,
                    columns=cols,
                    expression=expression,
                )
            )
        return results

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
        return batch_insert_rows(data, batch_size, lambda b: self._insert_batch(table_name, b))

    def _insert_batch(self, table_name: str, batch: list[dict[str, Any]]) -> int:
        """Actually write a batch of data.

        Args:
            table_name: Target table name.
            batch: A batch of row data, each row is a dict mapping column names to values.

        Returns:
            Number of rows inserted in this batch; returns 0 when batch is empty.
        """
        if not batch:
            return 0
        column_names = list(batch[0].keys())
        sql = build_insert_sql(table_name, column_names)
        values = [tuple(row[col] for col in column_names) for row in batch]
        self.conn.executemany(sql, values)
        self.conn.commit()
        return len(batch)

    def clear_table(self, table_name: str) -> None:
        """Clear table data and reset the autoincrement counter.

        Args:
            table_name: Target table name.
        """
        validate_table_name(table_name)
        safe_table = quote_identifier(table_name)
        self.conn.execute(f"DELETE FROM {safe_table}")
        # sqlite_sequence table only exists when at least one table uses AUTOINCREMENT.
        # Failure here is expected and non-critical.
        try:
            self.conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", [table_name])
        except sqlite3.Error:
            logger.debug("sqlite_sequence reset skipped", table_name=table_name)
        self.conn.commit()
        logger.debug("Cleared table", table_name=table_name)

    def restore_settings(self) -> None:
        """Restore the PRAGMA configuration prior to optimization, and commit the transaction."""
        super().restore_settings()
        self.conn.commit()

    def _execute_pragma(self, sql: str) -> None:
        """Execute a PRAGMA statement (called by PragmaOptimizer).

        Args:
            sql: PRAGMA statement string.
        """
        self.conn.execute(sql)

    def _fetch_pragma(self, name: str) -> Any:
        """Read the current PRAGMA value (called by PragmaOptimizer).

        Args:
            name: PRAGMA name (e.g. "synchronous").

        Returns:
            The first row and first column value of the PRAGMA; returns None when there is no result.
        """
        cursor = self.conn.execute(f"PRAGMA {name}")
        row = cursor.fetchone()
        return row[0] if row else None
