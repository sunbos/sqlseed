"""Bounded cycle support using existing keys, without backfill or rule changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.config.models import ColumnConfig, GeneratorConfig
from sqlseed.core.orchestrator import DataOrchestrator
from typing_extensions import Self

from sqlseed_web.messages import message as tr

if TYPE_CHECKING:
    from sqlseed.core.orchestrator._specs import ResolvedSpecs


def dependency_layers(dependencies: dict[str, set[str]]) -> tuple[list[str], list[list[str]]]:
    pending = {name: set(parents) for name, parents in dependencies.items()}
    layers: list[list[str]] = []
    while pending:
        if not (layer := [name for name, parents in pending.items() if not parents]):
            break
        layers.append(layer)
        for name in layer:
            del pending[name]
        for parents in pending.values():
            parents.difference_update(layer)
    return [name for layer in layers for name in layer], layers


def _finish_order(dependencies: dict[str, set[str]]) -> list[str]:
    visited: set[str] = set()
    finished: list[str] = []
    for start in dependencies:
        stack = [(start, False)]
        while stack:
            name, done = stack.pop()
            if done:
                finished.append(name)
            elif name not in visited:
                visited.add(name)
                stack.append((name, True))
                stack.extend((parent, False) for parent in sorted(dependencies[name], reverse=True))
    return finished


def cyclic_components(dependencies: dict[str, set[str]]) -> list[set[str]]:
    """Find SCCs iteratively, without marking blocked descendants as cycles."""
    children: dict[str, list[str]] = {name: [] for name in dependencies}
    for name, parents in dependencies.items():
        for parent in parents:
            children[parent].append(name)
    visited: set[str] = set()
    components: list[set[str]] = []
    for start in reversed(_finish_order(dependencies)):
        pending = [start]
        component: set[str] = set()
        while pending:
            if (name := pending.pop()) not in visited:
                visited.add(name)
                component.add(name)
                pending.extend(children[name])
        if len(component) > 1:
            components.append(component)
    return components


def schema_dependencies(config: GeneratorConfig, schema: dict[str, Any]) -> dict[str, set[str]]:
    selected = {table.name for table in config.tables}
    dependencies = {table.name: set[str]() for table in config.tables}
    for table in schema["tables"]:
        if table["name"] in selected:
            dependencies[table["name"]].update(
                fk["ref_table"]
                for fk in table["foreign_keys"]
                if fk["ref_table"] in selected and fk["ref_table"] != table["name"]
            )
    for association in config.associations:
        if association.source_table in selected:
            for name in association.target_tables:
                if name in selected and name != association.source_table:
                    dependencies[name].add(association.source_table)
    return dependencies


def _single_existing_source(source: dict[str, Any], tables: dict[str, Any]) -> bool:
    if not source["has_values"] or len(source["source_columns"]) != 1:
        return False
    foreign_keys = [fk for fk in tables[source["table"]]["foreign_keys"] if source["column"] in fk["columns"]]
    if len(foreign_keys) != 1:
        return False
    fk = foreign_keys[0]
    return bool(
        fk["ref_table"] == source["source_table"]
        and fk["columns"] == [source["column"]]
        and fk["ref_columns"] == source["source_columns"]
    )


def existing_cycle_sources(
    config: GeneratorConfig, schema: dict[str, Any], sources: list[dict[str, Any]], groups: list[set[str]]
) -> list[dict[str, Any]]:
    """Accept only SQLite cycles with existing single-column FK sources on every edge.

    Composite keys and configured associations retain the unsupported boundary.
    Presence of keys is not proof of UNIQUE/CHECK validity; normal sample checks
    and the atomic write transaction remain mandatory.
    """
    if schema["dialect"] != "sqlite":
        return []
    tables = {table["name"]: table for table in schema["tables"]}
    accepted: list[dict[str, Any]] = []
    for group in groups:
        internal = [
            source
            for source in sources
            if source["table"] != source["source_table"]
            and source["table"] in group
            and source["source_table"] in group
        ]
        if any(
            association.source_table in group and group.intersection(association.target_tables)
            for association in config.associations
        ):
            continue
        if internal and all(_single_existing_source(source, tables) for source in internal):
            accepted.extend(internal)
    return accepted


def read_source_values(orch: DataOrchestrator, table: str, columns: list[str]) -> list[dict[str, Any]]:
    quoted = [quote_identifier(column) for column in columns]
    return orch.query(
        f"SELECT DISTINCT {', '.join(quoted)} FROM {quote_identifier(table)} "
        f"WHERE {' AND '.join(f'{column} IS NOT NULL' for column in quoted)} "
        f"ORDER BY {', '.join(quoted)} LIMIT 10000"
    )


@dataclass(frozen=True)
class _CyclePool:
    table: str
    column: str
    values: list[Any]


class ExistingSourceOrchestrator(DataOrchestrator):
    """Keep accepted cycle edges on their pre-insert parent pool for this run."""

    cycle_pools: dict[tuple[str, str], _CyclePool] | None = None

    @classmethod
    def for_config(cls, config: GeneratorConfig) -> ExistingSourceOrchestrator:
        return cast("ExistingSourceOrchestrator", cls.from_config(config))

    def __enter__(self) -> Self:
        super().__enter__()
        return self

    def pin_cycle_sources(self, sources: list[dict[str, Any]]) -> None:
        self.cycle_pools = {}
        for source in sources:
            column = source["source_columns"][0]
            rows = read_source_values(self, source["source_table"], [column])
            self.cycle_pools[(source["table"], source["column"])] = _CyclePool(
                source["source_table"], column, [row[column] for row in rows]
            )

    def _resolve_specs(
        self,
        table_name: str,
        count: int,
        columns: dict[str, Any] | None,
        column_configs: list[ColumnConfig] | None,
        enrich: bool,
        *,
        clear_before: bool = False,
    ) -> ResolvedSpecs:
        resolved = super()._resolve_specs(table_name, count, columns, column_configs, enrich, clear_before=clear_before)
        for (table, column), pool in (self.cycle_pools or {}).items():
            if table != table_name:
                continue
            spec = resolved[0][column]
            if (
                not pool.values
                or spec.generator_name != "foreign_key"
                or spec.params.get("ref_table") != pool.table
                or spec.params.get("ref_column") != pool.column
            ):
                raise ValueError(tr("backend.workbench_runtime.cycle_source_rules_not_supported"))
            spec.params["_ref_values"] = list(pool.values)
        return resolved
