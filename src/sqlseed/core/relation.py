from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed.database._protocol import ForeignKeyInfo

logger = get_logger(__name__)


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
            if v not in existing:
                self._pools[column_name].append(v)
                existing.add(v)

    def clear(self) -> None:
        self._pools.clear()


class RelationResolver:
    def __init__(self, db_adapter: Any) -> None:
        self._db = db_adapter
        self._fk_cache: dict[str, list[ForeignKeyInfo]] = {}

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        if table_name not in self._fk_cache:
            self._fk_cache[table_name] = self._db.get_foreign_keys(table_name)
        return self._fk_cache[table_name]

    def get_dependencies(self, table_name: str) -> set[str]:
        fks = self.get_foreign_keys(table_name)
        return {fk.ref_table for fk in fks if fk.ref_table != table_name}

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

    def load_shared_pool(self, shared_pool: SharedPool, table_name: str) -> None:
        """Load generated values from shared pool into FK resolution."""
        for col_name, values in shared_pool._pools.items():
            fks = self.get_foreign_keys(table_name)
            for fk in fks:
                if fk.ref_column == col_name:
                    logger.debug(
                        "Loaded shared pool into FK",
                        table_name=table_name,
                        column_name=fk.column,
                        ref_column=col_name,
                        values_count=len(values),
                    )
