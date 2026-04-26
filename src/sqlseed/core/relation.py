from __future__ import annotations

import contextlib
import sqlite3
from typing import TYPE_CHECKING, Any

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
        self._fk_cache.clear()

    def _resolve_fk_or_integer_spec(
        self,
        table_name: str,
        col_name: str,
        spec: GeneratorSpec,
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
        if self._shared_pool.has(col_name):
            pool_values = self._shared_pool.get(col_name)
            logger.debug(
                "Resolved implicit association via SharedPool",
                table_name=table_name,
                column_name=col_name,
                pool_size=len(pool_values),
            )
            return _make_fk_pool_spec(col_name, pool_values, spec)
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
    ) -> dict[str, GeneratorSpec]:
        fks = self.get_foreign_keys(table_name)
        fk_columns = {fk.column for fk in fks}

        for col_name, spec in specs.items():
            if spec.generator_name == "foreign_key_or_integer":
                specs[col_name] = self._resolve_fk_or_integer_spec(table_name, col_name, spec)
            elif spec.generator_name == "foreign_key" and "ref_table" in spec.params:
                    ref_values = self._db.get_column_values(
                        spec.params["ref_table"],
                        spec.params["ref_column"],
                    )
                    spec.params["_ref_values"] = ref_values

        self._upgrade_fk_constrained_columns(table_name, specs, fk_columns)

        specs = self.apply_associations(table_name, specs)
        return self.resolve_implicit_associations(table_name, specs)

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
                with contextlib.suppress(ValueError, OSError, RuntimeError, sqlite3.OperationalError):
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
    ) -> dict[str, GeneratorSpec]:
        if not self._shared_pool:
            return specs

        for col_name, spec in list(specs.items()):
            if spec.generator_name != "foreign_key_or_integer":
                continue
            if not self._shared_pool.has(col_name):
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
        with contextlib.suppress(ValueError, OSError, RuntimeError, sqlite3.OperationalError):
            pk_columns = set(self._db.get_primary_keys(table_name))

        for col_name, spec in generator_specs.items():
            if spec.generator_name == "skip" and col_name not in pk_columns:
                continue
            with contextlib.suppress(ValueError, OSError, RuntimeError, sqlite3.OperationalError):
                values = self._db.get_column_values(table_name, col_name, limit=10000)
                if values:
                    self._shared_pool.merge(col_name, values)
                    if spec.generator_name == "skip" and col_name in pk_columns:
                        logger.debug(
                            "Registered auto-increment PK values to SharedPool",
                            table_name=table_name,
                            column_name=col_name,
                            value_count=len(values),
                        )
