"""Resolve FK dependencies for on-demand schema analysis.

Given a set of target tables, this resolver recursively finds all FK
parent tables (up to max_depth) to provide as LLM context. Target
tables generate YAML; context tables only provide schema information
for understanding relationships.

Cycle detection prevents infinite loops on self-referencing or
circular FK relationships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed.database._protocol import DatabaseAdapter, ForeignKeyInfo

logger = get_logger(__name__)


@dataclass(frozen=True)
class ResolvedTables:
    """Result of FK dependency resolution.

    Attributes:
        target_tables: Tables to generate YAML configs for.
        context_tables: FK parent tables (schema-only context for LLM).
        foreign_keys: All FK relationships discovered, keyed by table.
            Typed as ``dict[str, list[ForeignKeyInfo]]`` for mypy strict
            consistency with ``AnalysisRequest.foreign_keys``.
    """

    target_tables: list[str]
    context_tables: list[str]
    foreign_keys: dict[str, list[ForeignKeyInfo]] = field(default_factory=dict)


class DependencyResolver:
    """Resolve FK dependencies with recursion, cycle detection, depth limit.

    Args:
        db: Database adapter for FK introspection.
        max_depth: Maximum FK chain depth (default 5).
    """

    def __init__(self, db: DatabaseAdapter, *, max_depth: int = 5) -> None:
        self._db = db
        self._max_depth = max_depth

    def resolve(
        self,
        target_tables: list[str],
        *,
        include_dependencies: bool = True,
    ) -> ResolvedTables:
        """Resolve dependencies for target tables.

        Args:
            target_tables: Tables to generate configs for.
            include_dependencies: If True (default), recursively find FK
                parent tables as LLM context. If False, only target tables.

        Returns:
            ResolvedTables with target_tables and context_tables separated.
        """
        if not include_dependencies:
            return ResolvedTables(
                target_tables=list(target_tables),
                context_tables=[],
                foreign_keys={},
            )

        target_set = set(target_tables)
        context_tables: set[str] = set()
        all_fks: dict[str, list[ForeignKeyInfo]] = {}
        visited: set[str] = set(target_tables)

        for target in target_tables:
            self._collect_parents(
                table=target,
                context_tables=context_tables,
                all_fks=all_fks,
                visited=visited,
                depth=0,
                target_set=target_set,
            )

        context_tables -= target_set

        return ResolvedTables(
            target_tables=list(target_tables),
            context_tables=sorted(context_tables),
            foreign_keys=all_fks,
        )

    def _collect_parents(
        self,
        *,
        table: str,
        context_tables: set[str],
        all_fks: dict[str, list[ForeignKeyInfo]],
        visited: set[str],
        depth: int,
        target_set: set[str],
    ) -> None:
        """Recursively collect FK parent tables."""
        if depth >= self._max_depth:
            logger.debug(
                "FK dependency depth limit reached",
                table=table,
                depth=depth,
                max_depth=self._max_depth,
            )
            return

        try:
            fks = self._db.get_foreign_keys(table)
        except (ValueError, RuntimeError, OSError) as e:
            logger.debug("Failed to get FKs for table", table=table, error=str(e))
            return

        all_fks[table] = list(fks)

        for fk in fks:
            parent = fk.ref_table
            if parent in visited:
                continue
            visited.add(parent)
            if parent not in target_set:
                context_tables.add(parent)
            self._collect_parents(
                table=parent,
                context_tables=context_tables,
                all_fks=all_fks,
                visited=visited,
                depth=depth + 1,
                target_set=target_set,
            )
