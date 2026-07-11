"""Column dependency graph (DAG) construction and topological sorting.

ColumnDAG builds a directed acyclic graph based on column derive_from dependencies
and performs topological sorting using Kahn's algorithm to ensure derived columns
are generated after their source columns.

Starting from v4 (2026-07-08), the DAG also tracks ``row['col_name']``
references inside derive_from expressions. This ensures columns referenced
via ``row['...']`` are generated before the derived column, preventing
``KeyError`` at expression evaluation time.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlseed.core.mapper import GeneratorSpec

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo

# Matches row['col_name'] references in derive_from expressions.
# Used to extract implicit dependencies that the DAG must track.
_ROW_REF_RE = re.compile(r"row\[\s*['\"]([^'\"]+)['\"]\s*\]")


@dataclass
class ColumnConstraints:
    """Column-level constraints."""

    is_unique: bool = False
    min_value: int | float | None = None
    max_value: int | float | None = None
    regex: str | None = None
    max_retries: int = 100


@dataclass
class ColumnNode:
    """A node in the DAG representing a column."""

    name: str
    generator_spec: GeneratorSpec
    # All columns this node depends on — used for topological ordering.
    # Includes BOTH the explicit ``derive_from`` sources AND any implicit
    # ``row['col_name']`` references extracted from the expression. Keeping
    # these combined ensures the DAG schedules referenced columns before the
    # derived column, preventing ``KeyError`` at evaluation time.
    depends_on: list[str] = field(default_factory=list)
    # Only the EXPLICIT ``derive_from`` sources — used by the stream to
    # construct the ``value`` context variable. When ``derive_from`` is a
    # single string, ``value`` is a scalar; when it's a list, ``value`` is
    # a list. Implicit ``row['col_name']`` references MUST NOT be included
    # here, otherwise a single-source derive like
    # ``derive_from: registration_fee`` with expression
    # ``value + row['lab_fee']`` would be misclassified as multi-column
    # derive (``value`` becoming a list), breaking the expression.
    derive_from_sources: list[str] = field(default_factory=list)
    expression: str | None = None  # derived expression
    constraints: ColumnConstraints | None = None  # constraints
    is_derived: bool = False  # whether this is a derived column
    nullable: bool = True  # whether the column accepts NULL (from schema)

    @property
    def is_skip(self) -> bool:
        """Return True if the column's generator is a skip marker (no value produced).

        Two sentinel generator names are treated as skip markers:
        - ``"skip"``: returned by ColumnMapper L1 for autoincrement PK columns
          (detected via ``is_autoincrement`` flag from the schema inferrer).
        - ``"autoincrement"``: returned by ColumnMapper L5 pattern match
          (``r"^id$"`` rule) when L1 doesn't fire — e.g., PostgreSQL SERIAL
          columns where the schema inferrer doesn't set ``is_autoincrement=True``,
          or config-driven fills where the YAML explicitly sets
          ``generator: autoincrement`` (from ai-analyze output). Without this,
          the stream would try to call ``provider.generate("autoincrement", ...)``
          and raise ``UnknownGeneratorError``.
        """
        return self.generator_spec.generator_name in {"skip", "autoincrement"}


class ColumnDAG:
    """Builds and manages the column dependency graph."""

    def build(
        self,
        specs: dict[str, GeneratorSpec],
        column_configs: list[Any] | None = None,
        unique_columns: set[str] | None = None,
        column_infos: list[ColumnInfo] | None = None,
    ) -> list[ColumnNode]:
        """Build a DAG from generator specs and column configs, returning topologically sorted nodes.

        Args:
            specs: Mapping of column name to generator spec.
            column_configs: Optional list of column configs, used to extract constraints and derive relationships.
            unique_columns: Optional set of unique constraint columns, used to force-mark unique constraints.
            column_infos: Optional list of column schema info, used to propagate
                nullability (``ColumnInfo.nullable``) onto each :class:`ColumnNode`.
                When ``None``, all nodes default to ``nullable=True``.

        Returns:
            Topologically sorted list of ColumnNode, with derived columns placed after their source columns.

        Raises:
            ValueError: When a circular dependency is detected among columns.
        """
        nodes: dict[str, ColumnNode] = {}
        config_map: dict[str, Any] = {}
        unique_columns = unique_columns or set()

        # Build a name -> nullable map from schema info so nodes can carry
        # NOT NULL semantics down to the stream (prevents null_ratio from
        # producing NULLs that violate a NOT NULL constraint).
        nullable_map: dict[str, bool] = {}
        if column_infos is not None:
            for ci in column_infos:
                nullable_map[ci.name] = ci.nullable

        if column_configs:
            for cc in column_configs:
                if hasattr(cc, "name"):
                    config_map[cc.name] = cc

        for col_name, spec in specs.items():
            nodes[col_name] = self._build_node_from_spec(
                col_name,
                spec,
                config_map.get(col_name),
                col_name in unique_columns,
                nullable=nullable_map.get(col_name, True),
            )

        return self._topological_sort(nodes)

    def _build_node_from_spec(
        self,
        col_name: str,
        spec: GeneratorSpec,
        cc: Any | None,
        is_unique: bool,
        *,
        nullable: bool = True,
    ) -> ColumnNode:
        constraints = None
        expression = None
        depends_on = []
        derive_from_sources: list[str] = []
        is_derived = False
        final_spec = spec

        if cc:
            if hasattr(cc, "constraints") and cc.constraints:
                constraints = ColumnConstraints(
                    is_unique=cc.constraints.unique,
                    min_value=cc.constraints.min_value,
                    max_value=cc.constraints.max_value,
                    regex=cc.constraints.regex,
                    max_retries=cc.constraints.max_retries,
                )
            if hasattr(cc, "derive_from") and cc.derive_from:
                # Don't override foreign_key specs — relation.py sets these
                # for FK columns (including self-referencing FKs with empty
                # parent, where null_ratio=1.0 is critical for avoiding FK
                # violations). If the LLM also set derive_from for the same
                # column, the foreign_key spec takes precedence (FK integrity
                # is more important than the LLM's derive_from expression).
                # This mirrors the composite FK handling in
                # RelationResolver.resolve_composite_fks which clears
                # derive_from for composite FK columns.
                if spec.generator_name == "foreign_key":
                    # Keep the foreign_key spec, ignore derive_from
                    pass
                else:
                    df = cc.derive_from
                    # derive_from_sources holds ONLY the explicit derive_from
                    # sources (single string -> one element, list -> as-is).
                    # The stream uses this to decide whether ``value`` is a
                    # scalar (len <= 1) or a list (len > 1).
                    derive_from_sources = list(df) if isinstance(df, list) else [df]
                    # depends_on starts with the explicit sources, then adds
                    # implicit row['col_name'] references for DAG ordering.
                    depends_on = list(derive_from_sources)
                    expression = cc.expression
                    is_derived = True
                    final_spec = GeneratorSpec(generator_name="__derive__")
                    # Track implicit row['col_name'] dependencies in the
                    # expression. Without this, the DAG may schedule the
                    # derived column before columns it references via row[...],
                    # causing KeyError at expression evaluation time.
                    if expression:
                        for ref in _ROW_REF_RE.findall(expression):
                            if ref not in depends_on:
                                depends_on.append(ref)

        if is_unique:
            if constraints is None:
                constraints = ColumnConstraints(is_unique=True)
            elif not constraints.is_unique:
                constraints = ColumnConstraints(
                    is_unique=True,
                    min_value=constraints.min_value,
                    max_value=constraints.max_value,
                    regex=constraints.regex,
                    max_retries=constraints.max_retries,
                )

        return ColumnNode(
            name=col_name,
            generator_spec=final_spec,
            depends_on=depends_on,
            derive_from_sources=derive_from_sources,
            expression=expression,
            constraints=constraints,
            is_derived=is_derived,
            nullable=nullable,
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
