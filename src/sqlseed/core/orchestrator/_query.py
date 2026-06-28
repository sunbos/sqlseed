"""Query mixin: schema introspection, mapping diagnostics, and direct SQL execution.

Separated from the original ``orchestrator.py`` to isolate the concerns of
schema context construction, dialect detection, column introspection,
foreign key inspection, row counting, mapping diagnostics, and direct
SQL execution helpers (``execute``, ``query``, ``fetch_one``).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError as SAOperationalError

from sqlseed._utils.sql_safe import validate_table_name

if TYPE_CHECKING:
    from sqlseed.core.mapper import ColumnMapper
    from sqlseed.core.relation import RelationResolver
    from sqlseed.core.schema import SchemaInferrer
    from sqlseed.database._protocol import DatabaseAdapter

    from ._common import CoreCtx


class QueryMixin:
    """Mixin providing schema introspection, mapping diagnostics, and direct SQL execution.

    Owns ``get_schema_context``, ``_get_dialect_name``, ``get_column_names``,
    ``get_skippable_columns``, ``get_topological_table_order``,
    ``get_table_names``, ``get_column_info``, ``get_foreign_keys``,
    ``get_row_count``, ``map_column``, ``report``, ``get_column_mapping``,
    ``execute``, ``query``, and ``fetch_one``. Expects the host class to
    expose the ``ConnectionMixin`` accessors (``_ensure_connected``,
    ``_db``, ``_schema``, ``_mapper``, ``_relation``, ``_core``,
    ``_connected``, ``_db_path``) and the ``SpecResolverMixin`` method
    ``_resolve_specs``.
    """

    # Instance attributes provided by ConnectionMixin.
    _core: CoreCtx
    _connected: bool
    _db_path: str

    if TYPE_CHECKING:
        # Provided by ConnectionMixin as read-only properties.
        @property
        def _db(self) -> DatabaseAdapter: ...

        @property
        def _schema(self) -> SchemaInferrer: ...

        @property
        def _mapper(self) -> ColumnMapper: ...

        @property
        def _relation(self) -> RelationResolver: ...

        # Provided by ConnectionMixin when combined in DataOrchestrator.
        def _ensure_connected(self) -> None: ...

        # Provided by SpecResolverMixin when combined in DataOrchestrator.
        def _resolve_specs(
            self,
            table_name: str,
            count: int,
            columns: dict[str, Any] | None,
            column_configs: list[Any] | None,
            enrich: bool,
        ) -> tuple[dict[str, Any], dict[str, Any], set[str]]: ...

    def get_schema_context(self, table_name: str) -> dict[str, Any]:
        self._ensure_connected()
        validate_table_name(table_name)
        column_infos = self._schema.get_column_info(table_name)
        fks = self._db.get_foreign_keys(table_name)
        all_tables = self._db.get_table_names()

        indexes: list[dict[str, Any]] = []
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            idx_infos = self._schema.get_index_info(table_name)
            indexes = [{"name": idx.name, "columns": idx.columns, "unique": idx.unique} for idx in idx_infos]

        sample_data: list[dict[str, Any]] = []
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            sample_data = self._schema.get_sample_data(table_name, limit=5)

        distribution: list[dict[str, Any]] = []
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            distribution = self._schema.profile_column_distribution(table_name, limit=1000)

        return {
            "table_name": table_name,
            "columns": column_infos,
            "foreign_keys": fks,
            "indexes": indexes,
            "sample_data": sample_data,
            "all_table_names": all_tables,
            "distribution": distribution,
            "dialect": self._get_dialect_name(),
        }

    def _get_dialect_name(self) -> str:
        """Get the current database dialect name (sqlite/postgresql), used for AI analysis context.

        If the adapter does not expose a dialect attribute (e.g., RawSQLiteAdapter), defaults to "sqlite".
        """
        db = self._core.db
        if db is not None and hasattr(db, "dialect"):
            try:
                return str(db.dialect.name)
            except RuntimeError:
                pass
        return "sqlite"

    def get_column_names(self, table_name: str) -> set[str]:
        self._ensure_connected()
        return {c.name for c in self._schema.get_column_info(table_name)}

    def get_skippable_columns(self, table_name: str) -> set[str]:
        self._ensure_connected()
        return {
            c.name
            for c in self._schema.get_column_info(table_name)
            if (c.is_primary_key and c.is_autoincrement) or c.default is not None
        }

    def get_topological_table_order(self, table_names: list[str]) -> list[str]:
        self._ensure_connected()
        return self._relation.topological_sort(table_names)

    def get_table_names(self) -> list[str]:
        self._ensure_connected()
        return self._db.get_table_names()

    def get_column_info(self, table_name: str) -> list[Any]:
        self._ensure_connected()
        return self._schema.get_column_info(table_name)

    def get_foreign_keys(self, table_name: str) -> list[Any]:
        self._ensure_connected()
        return self._db.get_foreign_keys(table_name)

    def get_row_count(self, table_name: str) -> int:
        self._ensure_connected()
        return self._db.get_row_count(table_name)

    def map_column(self, column_info: Any) -> Any:
        return self._mapper.map_column(column_info)

    def report(self) -> str:
        if not self._connected:
            return "Not connected to any database."

        tables = self._db.get_table_names()
        lines = [f"Database: {self._db_path}", "=" * 50]
        for table in tables:
            count = self._db.get_row_count(table)
            lines.append(f"  {table}: {count} rows")
        return "\n".join(lines)

    def get_column_mapping(self, table_name: str) -> dict[str, Any]:
        """Get column-to-generator mapping for diagnostic display.

        This is the public API for the ``inspect --show-mapping`` CLI command.
        Returns the generator specs dict keyed by column name.
        """
        self._ensure_connected()
        specs, _, _ = self._resolve_specs(
            table_name,
            count=1,
            columns=None,
            column_configs=None,
            enrich=False,
        )
        return specs

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> Any:
        """Execute a SQL statement.

        Args:
            sql: The SQL statement to execute.
            params: Optional tuple of parameters for parameterized queries.

        Returns:
            A cursor object with the result.
        """
        self._ensure_connected()
        if params is None:
            params = ()
        return self._db.execute(sql, params)

    def query(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        """Execute a SELECT query and return results as a list of dictionaries.

        Args:
            sql: The SQL SELECT query to execute.
            params: Optional tuple of parameters for parameterized queries.

        Returns:
            A list of dictionaries, where each dictionary represents a row.
        """
        self._ensure_connected()
        cursor = self.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        """Execute a SELECT query and return a single row as a dictionary.

        Args:
            sql: The SQL SELECT query to execute.
            params: Optional tuple of parameters for parameterized queries.

        Returns:
            A dictionary representing the first row, or None if no rows found.
        """
        self._ensure_connected()
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row, strict=True))
