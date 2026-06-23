"""Column dependency graph (DAG) construction and topological sorting.

ColumnDAG builds a directed acyclic graph based on column derive_from dependencies
and performs topological sorting using Kahn's algorithm to ensure derived columns
are generated after their source columns.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from sqlseed.core.mapper import GeneratorSpec


@dataclass
class ColumnConstraints:
    """Column-level constraints."""

    unique: bool = False
    min_value: int | float | None = None
    max_value: int | float | None = None
    regex: str | None = None
    max_retries: int = 100


@dataclass
class ColumnNode:
    """A node in the DAG representing a column."""

    name: str
    generator_spec: GeneratorSpec
    depends_on: list[str] = field(default_factory=list)  # source column names this column depends on
    expression: str | None = None  # derived expression
    constraints: ColumnConstraints | None = None  # constraints
    is_derived: bool = False  # whether this is a derived column

    @property
    def is_skip(self) -> bool:
        return self.generator_spec.generator_name == "skip"


class ColumnDAG:
    """Builds and manages the column dependency graph."""

    def build(
        self,
        specs: dict[str, GeneratorSpec],
        column_configs: list[Any] | None = None,
        unique_columns: set[str] | None = None,
    ) -> list[ColumnNode]:
        """Build a DAG from generator specs and column configs, returning topologically sorted nodes.

        Args:
            specs: Mapping of column name to generator spec.
            column_configs: Optional list of column configs, used to extract constraints and derive relationships.
            unique_columns: Optional set of unique constraint columns, used to force-mark unique constraints.

        Returns:
            Topologically sorted list of ColumnNode, with derived columns placed after their source columns.

        Raises:
            ValueError: When a circular dependency is detected among columns.
        """
        nodes: dict[str, ColumnNode] = {}
        config_map: dict[str, Any] = {}
        unique_columns = unique_columns or set()

        if column_configs:
            for cc in column_configs:
                if hasattr(cc, "name"):
                    config_map[cc.name] = cc

        for col_name, spec in specs.items():
            nodes[col_name] = self._build_node_from_spec(
                col_name, spec, config_map.get(col_name), col_name in unique_columns
            )

        return self._topological_sort(nodes)

    def _build_node_from_spec(self, col_name: str, spec: GeneratorSpec, cc: Any | None, is_unique: bool) -> ColumnNode:
        constraints = None
        expression = None
        depends_on = []
        is_derived = False
        final_spec = spec

        if cc:
            if hasattr(cc, "constraints") and cc.constraints:
                constraints = ColumnConstraints(
                    unique=cc.constraints.unique,
                    min_value=cc.constraints.min_value,
                    max_value=cc.constraints.max_value,
                    regex=cc.constraints.regex,
                    max_retries=cc.constraints.max_retries,
                )
            if hasattr(cc, "derive_from") and cc.derive_from:
                depends_on = [cc.derive_from]
                expression = cc.expression
                is_derived = True
                final_spec = GeneratorSpec(generator_name="__derive__")

        if is_unique:
            if constraints is None:
                constraints = ColumnConstraints(unique=True)
            elif not constraints.unique:
                constraints = ColumnConstraints(
                    unique=True,
                    min_value=constraints.min_value,
                    max_value=constraints.max_value,
                    regex=constraints.regex,
                    max_retries=constraints.max_retries,
                )

        return ColumnNode(
            name=col_name,
            generator_spec=final_spec,
            depends_on=depends_on,
            expression=expression,
            constraints=constraints,
            is_derived=is_derived,
        )

    def _topological_sort(self, nodes: dict[str, ColumnNode]) -> list[ColumnNode]:
        """Topological sort using Kahn's algorithm."""
        in_degree: dict[str, int] = dict.fromkeys(nodes, 0)
        adjacency: dict[str, list[str]] = {name: [] for name in nodes}

        for name, node in nodes.items():
            for dep in node.depends_on:
                if dep in adjacency:
                    adjacency[dep].append(name)
                    in_degree[name] += 1

        queue = deque([name for name, deg in in_degree.items() if deg == 0])
        result: list[ColumnNode] = []

        while queue:
            current = queue.popleft()
            result.append(nodes[current])
            for neighbor in adjacency.get(current, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(nodes):
            raise ValueError("Circular dependency detected in column definitions")

        return result
