"""Schema inferrer: reads table structure from the database and infers column attributes.

Wraps the database adapter: provides query capabilities for column info, foreign keys,
primary keys, indexes, unique constraints, and column distribution profiling.
"""

from __future__ import annotations

import collections
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError as SAOperationalError

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import validate_table_name

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo, DatabaseAdapter, ForeignKeyInfo, IndexInfo

logger = get_logger(__name__)


class SchemaInferrer:
    """Schema inferrer: reads table structure based on the database adapter and infers column attributes.

    All table-name queries are validated first via _validate for safety:
    to avoid injection risks and unify exception handling.
    """

    def __init__(self, db_adapter: DatabaseAdapter) -> None:
        """Initialize the inferrer: bind a database adapter instance."""
        self._db = db_adapter

    def _validate(self, table_name: str) -> None:
        """Validate the table name: to prevent SQL injection."""
        validate_table_name(table_name)

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        """Return the list of column info for the specified table."""
        self._validate(table_name)
        return list(self._db.get_column_info(table_name))

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        """Return the list of foreign key info for the specified table."""
        self._validate(table_name)
        return list(self._db.get_foreign_keys(table_name))

    def get_table_names(self) -> list[str]:
        """Return a list of all user table names in the database."""
        return list(self._db.get_table_names())

    def get_primary_keys(self, table_name: str) -> list[str]:
        """Return the list of primary key column names for the specified table."""
        self._validate(table_name)
        return list(self._db.get_primary_keys(table_name))

    def get_table_schema(self, table_name: str) -> dict[str, ColumnInfo]:
        """Return a column-info dict indexed by column name."""
        columns = self.get_column_info(table_name)
        return {col.name: col for col in columns}

    def get_index_info(self, table_name: str) -> list[IndexInfo]:
        """Return the list of index info for the specified table."""
        self._validate(table_name)
        return list(self._db.get_index_info(table_name))

    def detect_unique_columns(self, table_name: str) -> set[str]:
        """Detect the set of columns with unique constraints in the table.

        Combines single-column unique indexes and non-autoincrement primary keys:
        any query failure only logs without raising an exception.
        """
        unique_cols: set[str] = set()
        try:
            indexes = self.get_index_info(table_name)
            for idx in indexes:
                if idx.unique and len(idx.columns) == 1:
                    unique_cols.add(idx.columns[0])
        except (ValueError, RuntimeError, OSError, SAOperationalError):
            logger.debug("Failed to detect unique constraints from indexes", table_name=table_name)

        try:
            pks = self._db.get_primary_keys(table_name)
            column_infos = self.get_column_info(table_name)
            autoincrement_pks = {c.name for c in column_infos if c.is_primary_key and c.is_autoincrement}
            for pk in pks:
                if pk not in autoincrement_pks:
                    unique_cols.add(pk)
        except (ValueError, RuntimeError, OSError, SAOperationalError):
            logger.debug("Failed to detect PK unique constraints", table_name=table_name)

        return unique_cols

    def detect_composite_unique_constraints(self, table_name: str) -> list[list[str]]:
        """Detect composite (multi-column) UNIQUE constraints on the table.

        Returns a list of column-name lists, each representing one composite
        UNIQUE constraint (e.g., ``UNIQUE(account_id, instrument_id)`` →
        ``[['account_id', 'instrument_id']]``). Single-column UNIQUE constraints
        are excluded (they are handled by ``detect_unique_columns`` and the
        per-column ``constraints.unique`` flag).

        Two sources are checked:

        1. ``get_index_info`` — returns explicit ``CREATE [UNIQUE] INDEX``
           indexes. On raw sqlite3 adapters, this also returns auto-indexes
           created by ``UNIQUE(...)`` constraints (via ``PRAGMA index_list``).
        2. ``get_unique_constraints`` — returns table-level ``UNIQUE(...)``
           constraints. On SQLAlchemy adapters, this is the ONLY way to detect
           them, because ``inspector.get_indexes`` excludes auto-indexes.

        Any query failure only logs without raising an exception.
        """
        composite: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        try:
            indexes = self.get_index_info(table_name)
            for idx in indexes:
                if idx.unique and len(idx.columns) > 1:
                    key = tuple(idx.columns)
                    if key not in seen:
                        seen.add(key)
                        composite.append(list(idx.columns))
        except (ValueError, RuntimeError, OSError, SAOperationalError):
            logger.debug(
                "Failed to detect composite UNIQUE constraints from indexes",
                table_name=table_name,
            )
        try:
            unique_constraints = self._db.get_unique_constraints(table_name)
            for uc in unique_constraints:
                if uc.unique and len(uc.columns) > 1:
                    key = tuple(uc.columns)
                    if key not in seen:
                        seen.add(key)
                        composite.append(list(uc.columns))
        except (ValueError, RuntimeError, OSError, SAOperationalError):
            logger.debug(
                "Failed to detect composite UNIQUE constraints from unique_constraints",
                table_name=table_name,
            )
        return composite

    def get_sample_data(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return the first few rows of sample data for the specified table: default 5 rows."""
        self._validate(table_name)
        return self._db.get_sample_rows(table_name, limit=limit)

    def profile_column_distribution(
        self,
        table_name: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Profile the distribution of each column in the table: sampling up to limit rows.

        Skips autoincrement primary key columns: returns per-column statistics including
        null ratio, distinct count, top values, and numeric range; returns an empty list
        when the table is empty.
        """
        self._validate(table_name)
        columns = self.get_column_info(table_name)
        row_count = self._db.get_row_count(table_name)

        if row_count == 0:
            return []

        profiles: list[dict[str, Any]] = []
        for col in columns:
            if col.is_primary_key and col.is_autoincrement:
                continue

            profile = self._profile_single_column(table_name, col.name, row_count, limit)
            profiles.append(profile)

        return profiles

    def _profile_single_column(
        self,
        table_name: str,
        column_name: str,
        total_rows: int,
        limit: int,
    ) -> dict[str, Any]:
        """Profile a single column's distribution.

        Returns null ratio, distinct count, top values, and numeric range statistics.
        """
        profile: dict[str, Any] = {"column": column_name}

        try:
            values = self._db.get_column_values(table_name, column_name, limit=limit)

            null_count = sum(1 for v in values if v is None)
            non_null_values = [v for v in values if v is not None]

            profile["null_ratio"] = round(null_count / len(values), 3) if values else 0.0
            profile["distinct_count"] = len(set(non_null_values))
            profile["sample_size"] = len(values)
            profile["total_rows"] = total_rows

            if non_null_values:
                counter = collections.Counter(non_null_values)
                top5 = counter.most_common(5)
                profile["top_values"] = [
                    {"value": str(v)[:50], "frequency": round(c / len(non_null_values), 3)} for v, c in top5
                ]
            else:
                profile["top_values"] = []

            # Exclude bool: in Python, bool is a subclass of int, so isinstance(True, int) is True.
            # Treating bool columns as numeric would produce misleading value_range stats.
            numeric_values = [v for v in non_null_values if isinstance(v, int | float) and not isinstance(v, bool)]
            if numeric_values:
                profile["value_range"] = {"min": min(numeric_values), "max": max(numeric_values)}
            else:
                profile["value_range"] = None

        except (ValueError, RuntimeError, OSError, SAOperationalError):
            profile["error"] = "failed to profile"

        return profile
