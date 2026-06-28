from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError as SAOperationalError

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import GeneratorSpec

if TYPE_CHECKING:
    from sqlseed.database._protocol import ForeignKeyInfo

logger = get_logger(__name__)


def _make_fk_pool_spec(col_name: str, pool_values: list[Any], spec: GeneratorSpec) -> GeneratorSpec:
    return GeneratorSpec(
        generator_name="foreign_key",
        params={
            "ref_table": "__shared_pool__",
            "ref_column": col_name,
            "strategy": "random",
            "_ref_values": pool_values,
        },
        null_ratio=spec.null_ratio,
        provider=spec.provider,
    )


class SharedPool:
    """Cross-table shared value pool for maintaining referential integrity."""

    def __init__(self) -> None:
        self._pools: dict[str, list[Any]] = {}

    def register(self, column_name: str, values: list[Any]) -> None:
        self._pools[column_name] = list(values)

    def get(self, column_name: str) -> list[Any]:
        return self._pools.get(column_name, [])

    def has(self, column_name: str) -> bool:
        return column_name in self._pools and len(self._pools[column_name]) > 0

    def merge(self, column_name: str, values: list[Any]) -> None:
        if column_name not in self._pools:
            self._pools[column_name] = []
        existing = set(self._pools[column_name])
        for v in values:
            try:
                if v not in existing:
                    self._pools[column_name].append(v)
                    existing.add(v)
            except TypeError:
                if v not in self._pools[column_name]:
                    self._pools[column_name].append(v)

    def clear(self) -> None:
        self._pools.clear()

    def items(self) -> dict[str, list[Any]]:
        return dict(self._pools)

    def __bool__(self) -> bool:
        return bool(self._pools)


class RelationResolver:
    def __init__(self, db_adapter: Any, shared_pool: SharedPool | None = None) -> None:
        self._db = db_adapter
        self._fk_cache: dict[str, list[ForeignKeyInfo]] = {}
        self._shared_pool = shared_pool if shared_pool is not None else SharedPool()
        self._associations: list[Any] = []

    def set_associations(self, associations: list[Any]) -> None:
        self._associations = associations

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        if table_name not in self._fk_cache:
            self._fk_cache[table_name] = self._db.get_foreign_keys(table_name)
        return self._fk_cache[table_name]

    def get_dependencies(self, table_name: str) -> set[str]:
        fks = self.get_foreign_keys(table_name)
        deps = {fk.ref_table for fk in fks if fk.ref_table != table_name}
        for assoc in self._associations:
            if table_name in assoc.target_tables and assoc.source_table != table_name:
                deps.add(assoc.source_table)
        return deps

    def topological_sort(self, table_names: list[str]) -> list[str]:
        graph: dict[str, set[str]] = {}
        for table in table_names:
            deps = self.get_dependencies(table)
            graph[table] = deps & set(table_names)

        visited: set[str] = set()
        temp_visited: set[str] = set()
        result: list[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            if node in temp_visited:
                raise ValueError(f"Circular dependency detected involving table: {node}")
            temp_visited.add(node)
            for dep in graph.get(node, set()):
                visit(dep)
            temp_visited.discard(node)
            visited.add(node)
            result.append(node)

        for table in table_names:
            visit(table)

        return result

    def resolve_foreign_key_values(
        self,
        table_name: str,
        column_name: str,
    ) -> list[Any]:
        fks = self.get_foreign_keys(table_name)
        for fk in fks:
            if fk.column == column_name:
                values: list[Any] = self._db.get_column_values(fk.ref_table, fk.ref_column)
                logger.debug(
                    "Resolved FK",
                    table_name=table_name,
                    column_name=column_name,
                    ref_table=fk.ref_table,
                    ref_column=fk.ref_column,
                    values_count=len(values),
                )
                return values
        return []

    def get_fk_info(self, table_name: str, column_name: str) -> ForeignKeyInfo | None:
        fks = self.get_foreign_keys(table_name)
        for fk in fks:
            if fk.column == column_name:
                return fk
        return None

    def clear_cache(self) -> None:
        """Clear the FK resolution cache.

        The cache is bound to the DataOrchestrator lifecycle and does not
        auto-invalidate on schema changes. Call this method if the database
        schema is modified at runtime.
        """
        self._fk_cache.clear()

    def _resolve_fk_or_integer_spec(
        self,
        table_name: str,
        col_name: str,
        spec: GeneratorSpec,
        column_types: dict[str, str] | None = None,
        unique_columns: set[str] | None = None,
    ) -> GeneratorSpec:
        fk_info = self.get_fk_info(table_name, col_name)
        if fk_info:
            ref_values = self.resolve_foreign_key_values(table_name, col_name)
            return GeneratorSpec(
                generator_name="foreign_key",
                params={
                    "ref_table": fk_info.ref_table,
                    "ref_column": fk_info.ref_column,
                    "strategy": "random",
                    "_ref_values": ref_values,
                },
                null_ratio=spec.null_ratio,
                provider=spec.provider,
            )
        is_unique = unique_columns is not None and col_name in unique_columns
        if self._shared_pool.has(col_name) and not is_unique:
            pool_values = self._shared_pool.get(col_name)
            logger.debug(
                "Resolved implicit association via SharedPool",
                table_name=table_name,
                column_name=col_name,
                pool_size=len(pool_values),
            )
            return _make_fk_pool_spec(col_name, pool_values, spec)

        col_type = (column_types or {}).get(col_name, "")
        if not col_type:
            logger.debug(
                "Column type not found, falling back to integer",
                table_name=table_name,
                column_name=col_name,
            )
        if any(t in col_type for t in ("VARCHAR", "TEXT", "CHAR", "CLOB")):
            return GeneratorSpec(
                generator_name="string",
                params={"min_length": 4, "max_length": 20},
                null_ratio=spec.null_ratio,
                provider=spec.provider,
            )
        return GeneratorSpec(
            generator_name="integer",
            params={"min_value": 1, "max_value": 999999},
            null_ratio=spec.null_ratio,
            provider=spec.provider,
        )

    def _upgrade_fk_constrained_columns(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
        fk_columns: set[str],
    ) -> None:
        for col_name in fk_columns:
            if col_name not in specs:
                continue
            spec = specs[col_name]
            if spec.generator_name in {"foreign_key", "foreign_key_or_integer"}:
                continue
            fk_info = self.get_fk_info(table_name, col_name)
            if fk_info is None:
                continue
            ref_values = self.resolve_foreign_key_values(table_name, col_name)
            specs[col_name] = GeneratorSpec(
                generator_name="foreign_key",
                params={
                    "ref_table": fk_info.ref_table,
                    "ref_column": fk_info.ref_column,
                    "strategy": "random",
                    "_ref_values": ref_values,
                },
                null_ratio=spec.null_ratio,
                provider=spec.provider,
            )
            logger.debug(
                "Upgraded column to foreign_key via FK constraint",
                table_name=table_name,
                column_name=col_name,
                ref_table=fk_info.ref_table,
                ref_column=fk_info.ref_column,
            )

    def resolve_foreign_keys(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
        unique_columns: set[str] | None = None,
    ) -> dict[str, GeneratorSpec]:
        fks = self.get_foreign_keys(table_name)
        fk_columns = {fk.column for fk in fks}

        column_types: dict[str, str] | None = None
        for col_name, spec in specs.items():
            if spec.generator_name == "foreign_key_or_integer":
                if column_types is None:
                    column_types = {c.name: c.type.upper() for c in self._db.get_column_info(table_name)}
                specs[col_name] = self._resolve_fk_or_integer_spec(
                    table_name,
                    col_name,
                    spec,
                    column_types=column_types,
                    unique_columns=unique_columns,
                )
            elif spec.generator_name == "foreign_key" and "ref_table" in spec.params:
                ref_values = self._db.get_column_values(
                    spec.params["ref_table"],
                    spec.params["ref_column"],
                )
                spec.params["_ref_values"] = ref_values

        self._upgrade_fk_constrained_columns(table_name, specs, fk_columns)

        specs = self.apply_associations(table_name, specs)
        return self.resolve_implicit_associations(table_name, specs, unique_columns=unique_columns)

    def _apply_single_association(
        self,
        table_name: str,
        assoc: Any,
        specs: dict[str, GeneratorSpec],
    ) -> None:
        col_name = assoc.column_name
        source_table = assoc.source_table
        source_col = assoc.source_column or assoc.column_name
        target_tables = assoc.target_tables

        if table_name not in target_tables:
            return
        if col_name not in specs:
            return
        spec = specs[col_name]
        if spec.generator_name == "foreign_key":
            return

        if not self._shared_pool.has(col_name):
            if self._shared_pool.has(source_col):
                pool_values = self._shared_pool.get(source_col)
                if pool_values:
                    self._shared_pool.merge(col_name, pool_values)
            else:
                with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
                    values = self._db.get_column_values(source_table, source_col, limit=10000)
                    if values:
                        self._shared_pool.merge(col_name, values)

        pool_values = self._shared_pool.get(col_name)
        if not pool_values:
            return

        specs[col_name] = _make_fk_pool_spec(col_name, pool_values, spec)
        logger.debug(
            "Applied explicit association from config",
            table_name=table_name,
            column_name=col_name,
            source_table=source_table,
            pool_size=len(pool_values),
        )

    def apply_associations(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
    ) -> dict[str, GeneratorSpec]:
        if not self._associations:
            return specs

        for assoc in self._associations:
            self._apply_single_association(table_name, assoc, specs)

        return specs

    def resolve_implicit_associations(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
        unique_columns: set[str] | None = None,
    ) -> dict[str, GeneratorSpec]:
        if not self._shared_pool:
            return specs

        for col_name, spec in list(specs.items()):
            if spec.generator_name != "foreign_key_or_integer":
                continue
            if not self._shared_pool.has(col_name):
                continue

            is_unique = unique_columns is not None and col_name in unique_columns
            if is_unique:
                logger.debug(
                    "Skipping implicit association for UNIQUE non-FK column",
                    table_name=table_name,
                    column_name=col_name,
                )
                continue

            pool_values = self._shared_pool.get(col_name)
            if not pool_values:
                continue

            specs[col_name] = _make_fk_pool_spec(col_name, pool_values, spec)
            logger.debug(
                "Resolved implicit association via SharedPool",
                table_name=table_name,
                column_name=col_name,
                pool_size=len(pool_values),
            )

        return specs

    def register_shared_pool(
        self,
        table_name: str,
        generator_specs: dict[str, GeneratorSpec],
    ) -> None:
        pk_columns: set[str] = set()
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            pk_columns = set(self._db.get_primary_keys(table_name))

        fk_columns: set[str] = set()
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            fk_columns = {fk.column for fk in self.get_foreign_keys(table_name)}

        # Collect PK/FK column names that need value fetching.
        target_columns = [
            col_name for col_name in generator_specs if col_name in pk_columns or col_name in fk_columns
        ]

        # Batch-fetch all PK/FK column values in a single query (avoids N+1 queries).
        # Pass target_columns so the adapter projects only the needed columns instead
        # of transferring all columns of wide tables (H5 data-transfer regression fix).
        sample_rows: list[dict[str, Any]] = []
        if target_columns:
            with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
                sample_rows = self._db.get_sample_rows(
                    table_name, limit=10000, columns=target_columns
                )

        for col_name, spec in generator_specs.items():
            if col_name not in pk_columns and col_name not in fk_columns:
                continue
            # Extract per-column values from the batch-fetched sample rows.
            values = [row[col_name] for row in sample_rows if col_name in row]
            if values:
                self._shared_pool.merge(col_name, values)
                if spec.generator_name == "skip" and col_name in pk_columns:
                    logger.debug(
                        "Registered auto-increment PK values to SharedPool",
                        table_name=table_name,
                        column_name=col_name,
                        value_count=len(values),
                    )
