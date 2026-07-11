"""Cross-table referential integrity resolution via foreign keys and a shared value pool.

Provides ``SharedPool`` (cross-table value reuse for implicit associations) and
``RelationResolver`` (foreign-key discovery, dependency ordering, and spec
rewriting for FK / association / shared-pool columns).
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError as SAOperationalError

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import quote_identifier
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
        """Register (replace) the value pool for a column."""
        self._pools[column_name] = list(values)

    def get(self, column_name: str) -> list[Any]:
        """Return the list of values registered for a column (empty if absent)."""
        return self._pools.get(column_name, [])

    def has(self, column_name: str) -> bool:
        """Return True if the pool has at least one value for the column."""
        return column_name in self._pools and len(self._pools[column_name]) > 0

    def merge(self, column_name: str, values: list[Any]) -> None:
        """Merge values into the column's pool, deduplicating against existing entries."""
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
        """Remove all column pools from the shared pool."""
        self._pools.clear()

    def items(self) -> dict[str, list[Any]]:
        """Return a shallow copy of all column pools as a dict."""
        return dict(self._pools)

    def __bool__(self) -> bool:
        return bool(self._pools)


class RelationResolver:
    """Resolves foreign-key and cross-table association specs against the database and shared pool.

    Caches foreign-key metadata per table, computes table dependencies for
    topological ordering, and rewrites column generator specs to draw values
    from referenced tables, explicit ``ColumnAssociation`` configs, or the
    implicit same-name shared pool.
    """

    def __init__(self, db_adapter: Any, shared_pool: SharedPool | None = None) -> None:
        self._db = db_adapter
        self._fk_cache: dict[str, list[ForeignKeyInfo]] = {}
        self._composite_fk_cache: dict[str, dict[str, tuple[str, str]]] = {}
        self._shared_pool = shared_pool if shared_pool is not None else SharedPool()
        self._associations: list[Any] = []

    def set_associations(self, associations: list[Any]) -> None:
        """Set the cross-table column associations used for implicit and explicit resolution."""
        self._associations = associations

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        """Return foreign keys for a table, caching the result on first access."""
        if table_name not in self._fk_cache:
            self._fk_cache[table_name] = self._db.get_foreign_keys(table_name)
        return self._fk_cache[table_name]

    def get_dependencies(self, table_name: str) -> set[str]:
        """Return the set of tables the given table depends on (FK targets and association sources)."""
        fks = self.get_foreign_keys(table_name)
        deps = {fk.ref_table for fk in fks if fk.ref_table != table_name}
        for assoc in self._associations:
            if table_name in assoc.target_tables and assoc.source_table != table_name:
                deps.add(assoc.source_table)
        return deps

    def topological_sort(self, table_names: list[str]) -> list[str]:
        """Return tables in dependency order so that referenced tables precede their dependents.

        Circular FK dependencies (e.g., A→B→A, common in real-world schemas
        like ``branches↔employees``) are broken gracefully using Kahn's
        algorithm: when no table has zero pending dependencies (cycle
        deadlock), a table is picked to break the cycle. The picker prefers
        tables whose FK to another remaining table is nullable — this allows
        ``null_ratio=1.0`` to be applied to the nullable side, avoiding FK
        violations when the NOT NULL side is filled later (with a populated
        shared pool). If no nullable FK is found, the first table in input
        order is used as fallback.
        """
        graph: dict[str, set[str]] = {}
        for table in table_names:
            deps = self.get_dependencies(table)
            graph[table] = deps & set(table_names)

        # Kahn's algorithm with cycle-breaking. pending_deps tracks the
        # set of unprocessed dependencies for each table. A table is
        # "ready" when its pending_deps is empty (all deps already placed
        # in the result). When no table is ready (cycle deadlock), the
        # cycle breaker picks a table whose FK to another remaining table
        # is nullable (so null_ratio=1.0 can be applied to that side).
        pending_deps: dict[str, set[str]] = {t: set(graph[t]) for t in table_names}
        remaining: set[str] = set(table_names)
        result: list[str] = []

        while remaining:
            ready = [t for t in table_names if t in remaining and not pending_deps[t]]
            if not ready:
                breaker = self._pick_cycle_breaker(table_names, remaining)
                logger.warning(
                    "Circular FK dependency detected, breaking cycle",
                    table=breaker,
                    remaining_tables=sorted(remaining),
                )
                ready = [breaker]
            for table in ready:
                if table not in remaining:
                    continue
                result.append(table)
                remaining.discard(table)
                # Remove this table from other tables' pending deps
                for t in remaining:
                    pending_deps[t].discard(table)

        return result

    def _pick_cycle_breaker(self, table_names: list[str], remaining: set[str]) -> str:
        """Pick a table to break a circular FK dependency.

        Prefers tables whose FK column to another remaining table is
        nullable — this allows ``null_ratio=1.0`` to be applied to the
        nullable side, avoiding FK violations when the NOT NULL side is
        filled later with a populated shared pool.

        Falls back to the first table in input order if no nullable FK
        is found (or if column info cannot be loaded).
        """
        for table in table_names:
            if table not in remaining:
                continue
            fks = self.get_foreign_keys(table)
            if not fks:
                continue
            # Check if any FK points to another remaining table and the
            # FK column is nullable. Self-referencing FKs are skipped
            # (they don't participate in the inter-table cycle).
            try:
                col_info = self._db.get_column_info(table)
            except Exception:
                continue
            nullable_map = {c.name: c.nullable for c in col_info}
            for fk in fks:
                if fk.ref_table == table or fk.ref_table not in remaining:
                    continue
                if nullable_map.get(fk.column, False):
                    return table
        # Fallback: first table in input order
        return next(t for t in table_names if t in remaining)

    def resolve_foreign_key_values(
        self,
        table_name: str,
        column_name: str,
    ) -> list[Any]:
        """Return the list of referenced values for a column that participates in a foreign key.

        Returns an empty list when the column is not a foreign key.
        """
        fks = self.get_foreign_keys(table_name)
        for fk in fks:
            if fk.column == column_name:
                values: list[Any] = self._db.get_column_values(fk.ref_table, fk.ref_column, limit=100000)
                if len(values) >= 100000:
                    logger.warning(
                        "FK parent table very large; consider using shared_pool strategy",
                        ref_table=fk.ref_table,
                        column=fk.ref_column,
                        sampled=len(values),
                    )
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
        """Return the foreign key info for a column, or None if it is not a foreign key."""
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
        self._composite_fk_cache.clear()

    def _get_composite_fk_targets(self, table_name: str) -> dict[str, tuple[str, str]]:
        """Detect composite FK columns and return their (ref_table, ref_column) mapping.

        Uses ``PRAGMA foreign_key_list`` and groups rows by the ``id`` field —
        rows sharing the same ``id`` belong to the same (possibly composite) FK
        constraint. Only columns from FK constraints with 2+ columns (composite
        FKs) are returned.

        This is needed because ``get_fk_info`` returns the first matching FK
        for a column (usually the single-column FK), but when a column is part
        of both a single-column FK and a composite FK, the composite FK's parent
        table is the correct sampling source. For example, in a schema with
        ``FOREIGN KEY (origin_wh_id) REFERENCES warehouses(id)`` and
        ``FOREIGN KEY (origin_wh_id, dest_wh_id) REFERENCES routes(origin_wh_id, dest_wh_id)``,
        ``origin_wh_id`` should sample from ``routes.origin_wh_id`` (the composite
        FK parent) rather than ``warehouses.id`` (the single-column FK parent),
        because the composite FK constraint is stricter.

        Returns:
            Dict mapping column_name -> (ref_table, ref_column) for composite FK
            columns. Empty dict if no composite FKs exist or the PRAGMA query
            fails (e.g., on non-SQLite backends).
        """
        groups = self._get_composite_fk_groups(table_name)
        result: dict[str, tuple[str, str]] = {}
        for cols in groups.values():
            for from_col, ref_table, to_col in cols:
                result[from_col] = (ref_table, to_col)
        return result

    def _get_composite_fk_groups(
        self, table_name: str
    ) -> dict[int, list[tuple[str, str, str]]]:
        """Detect composite FK groups and return them keyed by FK constraint id.

        Uses ``PRAGMA foreign_key_list`` and groups rows by the ``id`` field.
        Only groups with 2+ columns (composite FKs) are returned.

        Returns:
            Dict mapping fk_id -> list of (from_col, ref_table, to_col) tuples.
            The list preserves the ``seq`` order (column order within the FK).
            Empty dict if no composite FKs exist or the PRAGMA query fails.
        """
        # Cache key includes both the flat mapping and the grouped structure.
        # We store the groups in _composite_fk_cache under a sentinel key to
        # avoid a second cache dict, but keep the API clean by exposing only
        # the flat mapping via _get_composite_fk_targets.
        cache_key = f"__groups__:{table_name}"
        cached = self._composite_fk_cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        result: dict[int, list[tuple[str, str, str]]] = {}
        with contextlib.suppress(Exception):
            cursor = self._db.execute(f"PRAGMA foreign_key_list({quote_identifier(table_name)})")
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()

            fk_groups: dict[int, list[tuple[Any, Any, Any, Any]]] = {}
            for row in rows:
                fk_id, seq, ref_table, from_col, to_col, *_ = row
                fk_groups.setdefault(fk_id, []).append((seq, from_col, ref_table, to_col))

            for fk_id, entries in fk_groups.items():
                if len(entries) < 2:
                    continue  # Single-column FK, skip
                # Sort by seq to preserve column order within the FK
                entries.sort(key=lambda e: e[0])
                result[fk_id] = [(e[1], e[2], e[3]) for e in entries]

        self._composite_fk_cache[cache_key] = result  # type: ignore[assignment]
        return result

    def resolve_composite_fks(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
        user_configs: dict[str, Any] | None = None,
    ) -> dict[str, GeneratorSpec]:
        """Resolve composite FK columns to sample from the composite FK's parent table.

        For columns that are part of a composite FK (e.g.,
        ``FOREIGN KEY (a, b) REFERENCES routes(a, b)``), this method:

        1. Clears any ``derive_from`` in user_configs for the FIRST column of
           each composite FK group. The LLM may have set ``derive_from``
           (e.g., ``dest_wh_id`` deriving from ``origin_wh_id``) which overrides
           the GeneratorSpec in the DAG builder. But the first column must
           sample from its parent table column to get a valid starting value.

        2. For 2-column composite FKs, implements PAIR-LEVEL COORDINATION:
           - First column (col_a): set spec to ``foreign_key`` sampling from
             parent's first column (ref_a).
           - Second column (col_b): set user_config ``derive_from: col_a`` with
             expression ``lookup('parent', 'ref_b', value, 'ref_a')``. This
             guarantees the (col_a, col_b) pair always exists in the parent
             table, because col_b is looked up from the parent for the given
             col_a value. The ``lookup`` function is available in the
             ExpressionEngine when a db_adapter is supplied (which the
             orchestrator always does).

        3. For composite FKs with 3+ columns (rare), falls back to independent
           per-column sampling (known limitation — pair coordination is only
           implemented for 2-column composite FKs).

        The CHECK constraint (e.g., ``origin_wh_id != dest_wh_id``) is enforced
        separately by ``inequality_constraints`` in the DataStream, which retries
        rows that violate cross-column comparison constraints. When pair-level
        coordination is active, the CHECK is naturally satisfied because the
        pair comes from a real row in the parent table (which already satisfies
        its own CHECK constraints).
        """
        composite_groups = self._get_composite_fk_groups(table_name)
        if not composite_groups:
            return specs

        # Build a flat set of all composite FK columns for quick lookup.
        all_composite_cols: set[str] = set()
        for cols in composite_groups.values():
            for from_col, _ref_table, _to_col in cols:
                all_composite_cols.add(from_col)

        for _fk_id, cols in composite_groups.items():
            if len(cols) == 2:
                self._resolve_two_column_composite_fk(
                    table_name, cols, specs, user_configs
                )
            else:
                # 3+ column composite FK: fall back to independent per-column
                # sampling. Pair coordination for N>2 would require a chain of
                # derive_from expressions, which is complex and rare.
                self._resolve_multi_column_composite_fk(
                    table_name, cols, specs, user_configs
                )

        return specs

    def _resolve_two_column_composite_fk(
        self,
        table_name: str,
        cols: list[tuple[str, str, str]],
        specs: dict[str, GeneratorSpec],
        user_configs: dict[str, Any] | None,
    ) -> None:
        """Resolve a 2-column composite FK with pair-level coordination.

        ``cols`` is ``[(col_a, ref_table, ref_a), (col_b, ref_table, ref_b)]``.
        Sets col_a to ``foreign_key`` sampling from parent.ref_a, and col_b
        to ``derive_from: col_a`` with a ``lookup()`` expression that queries
        parent.ref_b for the given col_a value.
        """
        col_a, ref_table, ref_a = cols[0]
        col_b, _ref_table_b, ref_b = cols[1]

        # --- Column A: foreign_key spec sampling from parent.ref_a ---
        if col_a in specs:
            spec_a = specs[col_a]
            ref_values_a = self._db.get_column_values(ref_table, ref_a, limit=100000)
            specs[col_a] = GeneratorSpec(
                generator_name="foreign_key",
                params={
                    "ref_table": ref_table,
                    "ref_column": ref_a,
                    "strategy": "random",
                    "_ref_values": ref_values_a,
                },
                null_ratio=spec_a.null_ratio,
                provider=spec_a.provider,
            )
            # Clear any LLM-set derive_from on col_a so the foreign_key spec
            # takes effect in the DAG builder.
            if user_configs is not None:
                uc_a = user_configs.get(col_a)
                if uc_a is not None and hasattr(uc_a, "derive_from") and uc_a.derive_from:
                    uc_a.derive_from = None
                    uc_a.expression = None
            logger.debug(
                "Resolved composite FK first column (pair coordination)",
                table_name=table_name,
                column_name=col_a,
                ref_table=ref_table,
                ref_column=ref_a,
                values_count=len(ref_values_a),
            )

        # --- Column B: derive_from col_a via lookup expression ---
        # This guarantees (col_a, col_b) pair exists in parent table.
        if col_b not in specs:
            return
        spec_b = specs[col_b]

        # The DAG builder has a guard: if spec.generator_name == "foreign_key",
        # it keeps the foreign_key spec and ignores derive_from in user_configs.
        # So for col_b, we have two cases:
        #
        # 1. user_configs IS available (normal path): set col_b's spec to a
        #    neutral "integer" placeholder and set derive_from + expression in
        #    user_configs. The DAG will create a __derive__ node that evaluates
        #    the lookup expression, guaranteeing pair coordination.
        #
        # 2. user_configs is None (defensive fallback): set col_b's spec to
        #    foreign_key sampling from parent.ref_b. This does NOT guarantee
        #    pair coordination, but at least produces valid individual values.
        if user_configs is not None:
            # Case 1: use derive_from + lookup expression for pair coordination.
            specs[col_b] = GeneratorSpec(
                generator_name="integer",
                params={"min_value": 1, "max_value": 999999},
                null_ratio=spec_b.null_ratio,
                provider=spec_b.provider,
            )

            uc_b = user_configs.get(col_b)
            if uc_b is None:
                from sqlseed.config.models import ColumnConfig

                uc_b = ColumnConfig(name=col_b)
                user_configs[col_b] = uc_b

            # Set derive_from + expression. Clear generator to avoid the
            # "cannot use both generator and derive_from" validation error.
            uc_b.generator = None
            uc_b.params = {}
            uc_b.derive_from = col_a
            uc_b.expression = (
                f"lookup('{ref_table}', '{ref_b}', value, '{ref_a}')"
            )
            logger.debug(
                "Resolved composite FK second column (pair coordination via lookup)",
                table_name=table_name,
                column_name=col_b,
                derive_from=col_a,
                ref_table=ref_table,
                ref_column=ref_b,
            )
        else:
            # Case 2: defensive fallback — independent sampling (no pair coordination).
            ref_values_b = self._db.get_column_values(ref_table, ref_b, limit=100000)
            specs[col_b] = GeneratorSpec(
                generator_name="foreign_key",
                params={
                    "ref_table": ref_table,
                    "ref_column": ref_b,
                    "strategy": "random",
                    "_ref_values": ref_values_b,
                },
                null_ratio=spec_b.null_ratio,
                provider=spec_b.provider,
            )
            logger.warning(
                "Composite FK pair coordination unavailable (user_configs is None); "
                "falling back to independent sampling",
                table_name=table_name,
                column_name=col_b,
            )

    def _resolve_multi_column_composite_fk(
        self,
        table_name: str,
        cols: list[tuple[str, str, str]],
        specs: dict[str, GeneratorSpec],
        user_configs: dict[str, Any] | None,
    ) -> None:
        """Resolve a 3+ column composite FK with independent per-column sampling.

        This is a fallback for composite FKs with more than 2 columns. Each
        column samples independently from its parent table column. This does
        NOT guarantee the column tuple exists in the parent table — it's a
        known limitation. Pair coordination for N>2 columns would require a
        chain of derive_from expressions.
        """
        for col_name, ref_table, ref_col in cols:
            if col_name not in specs:
                continue
            spec = specs[col_name]

            # Clear derive_from in user_configs if present.
            if user_configs is not None:
                uc = user_configs.get(col_name)
                if uc is not None and hasattr(uc, "derive_from") and uc.derive_from:
                    uc.derive_from = None
                    uc.expression = None
                    logger.debug(
                        "Cleared derive_from for composite FK column",
                        table_name=table_name,
                        column_name=col_name,
                    )

            ref_values = self._db.get_column_values(ref_table, ref_col, limit=100000)
            specs[col_name] = GeneratorSpec(
                generator_name="foreign_key",
                params={
                    "ref_table": ref_table,
                    "ref_column": ref_col,
                    "strategy": "random",
                    "_ref_values": ref_values,
                },
                null_ratio=spec.null_ratio,
                provider=spec.provider,
            )
            logger.debug(
                "Resolved composite FK column (independent, N>2)",
                table_name=table_name,
                column_name=col_name,
                ref_table=ref_table,
                ref_column=ref_col,
                values_count=len(ref_values),
            )

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
            # Empty parent + nullable column: when the FK target table has no
            # rows yet (either because it's a self-referencing FK and the table
            # is being filled for the first time, or because a cyclic FK
            # dependency means the parent table hasn't been filled yet), and
            # the column is nullable, force null_ratio=1.0 to avoid FK
            # violations (all rows get NULL). If NOT NULL, fall through with
            # empty ref_values — the generator will use the fallback integer
            # range.
            null_ratio = spec.null_ratio
            if not ref_values:
                col_nullable = True
                try:
                    col_info = self._db.get_column_info(table_name)
                    for c in col_info:
                        if c.name == col_name:
                            col_nullable = c.nullable
                            break
                except Exception:
                    pass
                if col_nullable:
                    null_ratio = 1.0
            return GeneratorSpec(
                generator_name="foreign_key",
                params={
                    "ref_table": fk_info.ref_table,
                    "ref_column": fk_info.ref_column,
                    "strategy": "random",
                    "_ref_values": ref_values,
                },
                null_ratio=null_ratio,
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
        # Fetch column info once for nullability checks (self-referencing FK
        # handling below needs to know whether the column permits NULL).
        column_info_map: dict[str, bool] = {}
        for col_name in fk_columns:
            if col_name not in specs:
                continue
            spec = specs[col_name]
            if spec.generator_name == "foreign_key":
                # If _resolve_fk_or_integer_spec already upgraded this to
                # foreign_key with null_ratio=1.0 (empty parent + nullable),
                # we still need to fix any conditional column linked via
                # bidirectional CHECK (e.g., org_type='root' OR parent_id IS
                # NOT NULL). Without this, the conditional column gets random
                # values that violate the CHECK when the FK is NULL.
                if (
                    spec.null_ratio == 1.0
                    and not spec.params.get("_ref_values")
                ):
                    self._fix_conditional_column_for_null_fk(
                        table_name, col_name, specs
                    )
                continue
            if spec.generator_name == "foreign_key_or_integer":
                # Only process foreign_key_or_integer for self-ref FK
                # handling; other foreign_key_or_integer columns are
                # resolved later by _resolve_fk_or_integer_spec.
                fk_info_peek = self.get_fk_info(table_name, col_name)
                if fk_info_peek is None or fk_info_peek.ref_table != table_name:
                    continue
                # Fall through to self-ref FK handling below
            fk_info = self.get_fk_info(table_name, col_name)
            if fk_info is None:
                continue
            ref_values = self.resolve_foreign_key_values(table_name, col_name)
            # Empty parent handling: when the parent table is the same as the
            # current table (self-referencing FK, e.g.,
            # ``departments.parent_id REFERENCES departments(id)``), or when a
            # cyclic FK dependency means the parent table hasn't been filled
            # yet, the parent is empty at spec resolution time. Without
            # special handling, the empty ``_ref_values`` causes the generator
            # to fall back to a random integer in [1, 999999], producing FK
            # violations.
            #
            # Fix: if the column is nullable, force ``null_ratio=1.0`` so all
            # rows get NULL (valid for nullable FKs). This avoids FK
            # violations while preserving data integrity. A two-pass approach
            # (insert then update) would produce richer hierarchies but
            # requires orchestrator-level changes.
            if not ref_values:
                if not column_info_map:
                    column_info_map = {c.name: c.nullable for c in self._db.get_column_info(table_name)}
                col_nullable = column_info_map.get(col_name, True)
                if col_nullable:
                    specs[col_name] = GeneratorSpec(
                        generator_name="foreign_key",
                        params={
                            "ref_table": fk_info.ref_table,
                            "ref_column": fk_info.ref_column,
                            "strategy": "random",
                            "_ref_values": ref_values,
                            "_fallback_min": 1,
                            "_fallback_max": 1,
                        },
                        null_ratio=1.0,
                        provider=spec.provider,
                    )
                    logger.debug(
                        "FK with empty parent, set null_ratio=1.0",
                        table_name=table_name,
                        column_name=col_name,
                        ref_table=fk_info.ref_table,
                    )
                    # Bidirectional CHECK constraint handling: when a self-ref
                    # FK column is forced to NULL (null_ratio=1.0), any
                    # conditional column linked via a bidirectional CHECK
                    # (e.g., ``org_type = 'root' OR parent_id IS NOT NULL``)
                    # must be set to its null_val ('root' in this example) to
                    # satisfy the CHECK during initial fill. Without this,
                    # 75% of rows violate the CHECK when the conditional
                    # column has multiple choices (e.g., root/division/team).
                    # The _post_fill_self_ref_fks pass later updates ~70% of
                    # rows to reference existing PKs and adjusts the
                    # conditional column accordingly.
                    self._fix_conditional_column_for_null_fk(
                        table_name, col_name, specs
                    )
                    continue
                # NOT NULL self-referencing FK with empty parent: fall through
                # to the default upgrade (will use fallback integers). This is
                # a known limitation — a two-pass fill would be needed.
            # Preserve the original spec's min_value/max_value so that when the
            # parent table is empty (empty _ref_values), the FK fallback in
            # DataStream._handle_foreign_key can generate values within the
            # user-configured range instead of falling back to 999999.
            original_min = spec.params.get("min_value", 1)
            original_max = spec.params.get("max_value", 999999)
            specs[col_name] = GeneratorSpec(
                generator_name="foreign_key",
                params={
                    "ref_table": fk_info.ref_table,
                    "ref_column": fk_info.ref_column,
                    "strategy": "random",
                    "_ref_values": ref_values,
                    "_fallback_min": original_min,
                    "_fallback_max": original_max,
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

    def _fix_conditional_column_for_null_fk(
        self,
        table_name: str,
        fk_col: str,
        specs: dict[str, GeneratorSpec],
    ) -> None:
        """Fix conditional column linked to a NULL FK via bidirectional CHECK.

        When a self-referencing FK column is forced to NULL (null_ratio=1.0)
        because the parent table is empty, any conditional column linked via
        a bidirectional CHECK constraint must be set to its null_val to
        satisfy the CHECK during initial fill.

        Examples:
            CHECK (org_type = 'root' OR parent_id IS NOT NULL)  -- string
            CHECK (level = 1 OR parent_id IS NOT NULL)           -- integer

        When parent_id is NULL, org_type MUST be 'root' (or level MUST be 1)
        to satisfy the CHECK. This method detects such patterns and overrides
        the conditional column's spec to a choice generator with only
        [null_val], ensuring all initial rows satisfy the CHECK. The
        _post_fill_self_ref_fks pass later updates ~70% of rows to
        reference existing PKs and adjusts the conditional column to
        non-null_val values.
        """
        try:
            checks = self._db.get_check_constraints(table_name)
        except Exception:
            return

        # Detect bidirectional CHECK: cond_col = VALUE OR fk_col IS NOT NULL
        # (or reversed: fk_col IS NOT NULL OR cond_col = VALUE)
        # VALUE can be a string ('root') or an integer (1).
        cond_col: str | None = None
        null_val: str | int | None = None
        for check in checks:
            expr = check.expression if hasattr(check, "expression") else str(check)
            # Pattern: cond_col = 'VALUE' OR fk_col IS NOT NULL (string)
            m = re.search(
                rf"(\w+)\s*=\s*'([^']+)'\s+OR\s+{re.escape(fk_col)}\s+IS\s+NOT\s+NULL",
                expr,
                re.IGNORECASE,
            )
            if m:
                cond_col, null_val = m.group(1), m.group(2)
                break
            # Pattern: cond_col = NUMBER OR fk_col IS NOT NULL (integer)
            m = re.search(
                rf"(\w+)\s*=\s*(\d+)\s+OR\s+{re.escape(fk_col)}\s+IS\s+NOT\s+NULL",
                expr,
                re.IGNORECASE,
            )
            if m:
                cond_col, null_val = m.group(1), int(m.group(2))
                break
            # Pattern: fk_col IS NOT NULL OR cond_col = 'VALUE' (string)
            m = re.search(
                rf"{re.escape(fk_col)}\s+IS\s+NOT\s+NULL\s+OR\s+(\w+)\s*=\s*'([^']+)'",
                expr,
                re.IGNORECASE,
            )
            if m:
                cond_col, null_val = m.group(1), m.group(2)
                break
            # Pattern: fk_col IS NOT NULL OR cond_col = NUMBER (integer)
            m = re.search(
                rf"{re.escape(fk_col)}\s+IS\s+NOT\s+NULL\s+OR\s+(\w+)\s*=\s*(\d+)",
                expr,
                re.IGNORECASE,
            )
            if m:
                cond_col, null_val = m.group(1), int(m.group(2))
                break

        if cond_col is None or null_val is None:
            return
        if cond_col not in specs:
            return

        # Override the conditional column's spec to a choice with only [null_val]
        old_spec = specs[cond_col]
        specs[cond_col] = GeneratorSpec(
            generator_name="choice",
            params={"choices": [null_val]},
            null_ratio=0.0,
            provider=old_spec.provider,
        )
        logger.debug(
            "Fixed conditional column for NULL FK",
            table_name=table_name,
            fk_col=fk_col,
            cond_col=cond_col,
            null_val=null_val,
        )

    def resolve_foreign_keys(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
        unique_columns: set[str] | None = None,
    ) -> dict[str, GeneratorSpec]:
        """Resolve foreign key and association specs for every column in the table.

        Upgrades ``foreign_key_or_integer`` specs to concrete ``foreign_key`` or
        type-faithful fallbacks, hydrates explicit ``foreign_key`` specs with
        referenced values, upgrades FK-constrained columns, and finally applies
        explicit and implicit associations via the shared pool.
        """
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
        """Apply explicit ``ColumnAssociation`` configs to the column specs of the given table."""
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
        """Rewrite ``foreign_key_or_integer`` specs to draw from the shared pool by column name.

        Skips columns marked as UNIQUE (non-FK) so implicit reuse does not violate uniqueness.
        """
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
        """Register PK and FK column values for the table into the shared pool.

        Used after a table is filled so that downstream tables referencing the
        same column names (implicit associations) can reuse the generated values.
        """
        pk_columns: set[str] = set()
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            pk_columns = set(self._db.get_primary_keys(table_name))

        fk_columns: set[str] = set()
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            fk_columns = {fk.column for fk in self.get_foreign_keys(table_name)}

        # Collect PK/FK column names that need value fetching.
        target_columns = [col_name for col_name in generator_specs if col_name in pk_columns or col_name in fk_columns]

        # Batch-fetch all PK/FK column values in a single query (avoids N+1 queries).
        # Pass target_columns so the adapter projects only the needed columns instead
        # of transferring all columns of wide tables (H5 data-transfer regression fix).
        sample_rows: list[dict[str, Any]] = []
        if target_columns:
            with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
                sample_rows = self._db.get_sample_rows(table_name, limit=10000, columns=target_columns)

        if len(sample_rows) >= 10000:
            actual_count = 0
            with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
                actual_count = self._db.get_row_count(table_name)
            if actual_count > 10000:
                logger.warning(
                    "SharedPool truncated for large table; FK diversity may be limited",
                    table_name=table_name,
                    sampled=len(sample_rows),
                    total=actual_count,
                )

        for col_name, spec in generator_specs.items():
            if col_name not in pk_columns and col_name not in fk_columns:
                continue
            # Extract per-column values from the batch-fetched sample rows.
            values = [row[col_name] for row in sample_rows if col_name in row]
            if values:
                self._shared_pool.merge(col_name, values)
                if spec.generator_name in {"skip", "autoincrement"} and col_name in pk_columns:
                    logger.debug(
                        "Registered auto-increment PK values to SharedPool",
                        table_name=table_name,
                        column_name=col_name,
                        value_count=len(values),
                    )
