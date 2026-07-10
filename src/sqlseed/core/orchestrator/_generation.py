"""Generation mixin: batch generation, fill, and preview entry points.

Separated from the original ``orchestrator.py`` to isolate the concerns of
batch generation and insertion, the public ``fill_table`` flow (pragma
optimization, spec preparation, stream build, batch write, shared pool
registration, hook notification), and the ``preview_table`` flow.
"""

from __future__ import annotations

import contextlib
import random
import re
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.exc import SQLAlchemyError

from sqlseed._utils.logger import get_logger
from sqlseed._utils.progress import ProgressBackend, create_progress
from sqlseed._utils.sql_safe import quote_identifier, validate_table_name
from sqlseed.core.result import GenerationResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed._utils.metrics import MetricsCollector
    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.core.plugin_mediator import PluginMediator
    from sqlseed.core.relation import RelationResolver, SharedPool
    from sqlseed.core.stream import DataStream
    from sqlseed.database._protocol import DatabaseAdapter
    from sqlseed.plugins.manager import PluginManager

logger = get_logger(__name__)


def _detect_cond_column(
    fk_col: str,
    checks: list[Any],
) -> tuple[str | None, str | None]:
    """Detect conditional column linked to self-ref FK via bidirectional CHECK.

    Looks for patterns like:
        cond_col = 'VALUE' OR fk_col IS NOT NULL
        fk_col IS NOT NULL OR cond_col = 'VALUE'

    Returns (cond_col, null_val) where null_val is the value cond_col must
    have when fk_col is NULL. Returns (None, None) if no pattern matches.
    """
    for check in checks:
        expr = check.expression
        m = re.search(
            rf"(\w+)\s*=\s*'([^']+)'\s+OR\s+{re.escape(fk_col)}\s+IS\s+NOT\s+NULL",
            expr,
            re.IGNORECASE,
        )
        if m:
            return m.group(1), m.group(2)
        m = re.search(
            rf"{re.escape(fk_col)}\s+IS\s+NOT\s+NULL\s+OR\s+(\w+)\s*=\s*'([^']+)'",
            expr,
            re.IGNORECASE,
        )
        if m:
            return m.group(1), m.group(2)
    return None, None


def _extract_non_null_values(
    cond_col: str,
    null_val: str,
    checks: list[Any],
) -> list[str]:
    """Extract valid non-null values for cond_col from IN constraint.

    Looks for ``cond_col IN ('V1', 'V2', ...)`` and returns the values
    excluding ``null_val``.
    """
    for check in checks:
        m = re.search(
            rf"{re.escape(cond_col)}\s+IN\s*\(([^)]+)\)",
            check.expression,
            re.IGNORECASE,
        )
        if m:
            values = re.findall(r"'([^']+)'", m.group(1))
            return [v for v in values if v != null_val]
    return []


class GenerationMixin:
    """Mixin providing batch generation, fill, and preview entry points.

    Owns ``_generate_and_insert_batches``, ``fill_table``, and
    ``preview_table``. Expects the host class to expose the
    ``ConnectionMixin`` accessors (``_ensure_connected``, ``_db``,
    ``_plugins``, ``_plugin_mediator``, ``_metrics``, ``_optimize_pragma``,
    ``_relation``, ``_shared_pool``) and the ``SpecResolverMixin`` methods
    (``_prepare_specs``, ``_build_stream``, ``_resolve_specs``).
    """

    # Instance attribute provided by ConnectionMixin.
    _optimize_pragma: bool

    if TYPE_CHECKING:
        # Provided by ConnectionMixin as read-only properties. Split into two
        # TYPE_CHECKING blocks to keep each block's McCabe complexity under
        # pylint's too-complex threshold (10). The first block groups the
        # Connection accessors; the second groups the spec-resolver methods.
        @property
        def _db(self) -> DatabaseAdapter: ...

        @property
        def _plugins(self) -> PluginManager: ...

        @property
        def _plugin_mediator(self) -> PluginMediator | None: ...

        @property
        def _metrics(self) -> MetricsCollector: ...

        @property
        def _relation(self) -> RelationResolver: ...

        @property
        def _shared_pool(self) -> SharedPool: ...

        # Provided by ConnectionMixin when combined in DataOrchestrator.
        def _ensure_connected(self) -> None: ...

    if TYPE_CHECKING:
        # Cross-mixin methods — actual implementations in SpecResolverMixin.
        # Declared as ``Callable[..., T]`` to preserve return type checking
        # without duplicating the full parameter signatures (which would
        # trigger CodeDuplication with _specs.py). Argument checking is
        # deferred to DataOrchestrator, where mypy sees the real method.
        _prepare_specs: Callable[..., tuple[dict[str, Any], dict[str, Any], set[str], list[list[str]]]]
        _build_stream: Callable[..., DataStream]
        _resolve_specs: Callable[..., tuple[dict[str, Any], dict[str, Any], set[str], list[list[str]]]]
        # Cross-mixin methods — actual implementations in QueryMixin.
        query: Callable[..., list[dict[str, Any]]]
        execute: Callable[..., Any]

    def _generate_and_insert_batches(
        self,
        table_name: str,
        stream: DataStream,
        count: int,
        batch_size: int,
        progress: ProgressBackend | None = None,
        task_id: Any | None = None,
    ) -> tuple[int, int]:
        """Generate and write data batch by batch, triggering before/after_insert plugin hooks.

        Each batch executes in order: sqlseed_before_insert hook, PluginMediator batch transform,
        batch_insert write, metrics recording, sqlseed_after_insert hook, progress update.
        When progress is not passed in, an internal progress bar is created and its lifecycle managed.

        Args:
            table_name: Target table name.
            stream: Data stream, producing dict rows per batch.
            count: Total number of rows to generate.
            batch_size: Desired batch size; actual batch size is adaptively adjusted based on count.
            progress: Optional progress bar instance; created internally when None.
            task_id: Optional progress task ID; added internally when None.

        Returns:
            A tuple (total_inserted, batch_count).
        """
        total_inserted = 0
        batch_count = 0
        effective_batch_size = min(batch_size, count)
        if effective_batch_size > 0:
            desired_batches = max(1, min(10, count // effective_batch_size))
            effective_batch_size = max(count // desired_batches, 1)
        own_progress = progress is None
        with contextlib.ExitStack() as stack:
            if own_progress:
                progress = create_progress()
                stack.enter_context(progress)
            if progress is None:
                raise RuntimeError("Progress tracker not initialized. This is an internal error.")
            if task_id is None:
                task_id = progress.add_task(f"Generating {table_name}", total=count)
            for batch in stream.generate(count, effective_batch_size):
                batch_count += 1

                self._plugins.hook.sqlseed_before_insert(
                    table_name=table_name,
                    batch_number=batch_count,
                    batch_size=len(batch),
                )

                if self._plugin_mediator is not None:
                    current_batch = self._plugin_mediator.apply_batch_transforms(table_name, batch)
                else:
                    current_batch = batch

                inserted = self._db.batch_insert(table_name, iter(current_batch), batch_size)
                total_inserted += inserted

                self._metrics.record(f"{table_name}.batch_insert", float(inserted))

                self._plugins.hook.sqlseed_after_insert(
                    table_name=table_name,
                    batch_number=batch_count,
                    rows_inserted=inserted,
                )

                progress.update(task_id, advance=len(batch))
        return total_inserted, batch_count

    def fill_table(
        self,
        table_name: str,
        *,
        count: int = 1000,
        columns: dict[str, Any] | None = None,
        seed: int | None = None,
        batch_size: int = 5000,
        clear_before: bool = False,
        column_configs: list[Any] | None = None,
        transform: str | None = None,
        enrich: bool = False,
        skip_ai: bool = False,
    ) -> GenerationResult:
        """Batch-generate and write test data to the specified table, returning the generation result.

        Full flow: connection init -> table name validation -> pragma optimization ->
        spec preparation (_prepare_specs) -> data stream build (_build_stream) ->
        batch generation & write (_generate_and_insert_batches) -> shared pool registration ->
        hook notification. Catches ValueError/RuntimeError/OSError and sqlalchemy.exc
        exceptions, returning a GenerationResult with an errors field instead of raising.

        Args:
            table_name: Target table name.
            count: Number of rows to generate, must be greater than 0.
            columns: Optional simple column config dict (column name -> string/dict).
            seed: Optional random seed, for reproducible results.
            batch_size: Batch size, default 5000.
            clear_before: Whether to clear the table before generation, default False.
            column_configs: Optional list of ColumnConfig objects (full column config).
            transform: Optional user transform script path, defining a transform_row function.
            enrich: Whether to enable enrichment mode (identify enumeration columns based on
                existing data), default False.
            skip_ai: Whether to skip AI suggestions and template pool application, default False.

        Returns:
            GenerationResult containing table_name, count, elapsed, batch_count;
            on failure the errors field carries exception info.
        """
        self._ensure_connected()
        validate_table_name(table_name)
        if count <= 0:
            raise ValueError(f"count must be greater than 0, got {count}")
        start_time = time.monotonic()
        total_inserted = 0
        batch_count = 0

        progress = create_progress()
        with contextlib.ExitStack() as stack:
            stack.enter_context(progress)
            try:
                prep_task = progress.add_task(f"Preparing {table_name}...", total=None)

                if self._optimize_pragma:
                    self._db.optimize_for_bulk_write(count)

                progress.update(prep_task, description=f"Resolving schema for {table_name}...")
                generator_specs, user_configs, unique_columns, composite_unique = self._prepare_specs(
                    table_name, count, columns, column_configs, enrich, clear_before, skip_ai
                )

                progress.update(prep_task, description=f"Building data stream for {table_name}...")
                stream = self._build_stream(
                    generator_specs,
                    user_configs,
                    unique_columns,
                    transform,
                    seed,
                    table_name=table_name,
                    composite_unique=composite_unique,
                )

                progress.remove_task(prep_task)
                gen_task = progress.add_task(f"Generating {table_name}", total=count)

                self._plugins.hook.sqlseed_before_generate(
                    table_name=table_name,
                    count=count,
                    config=None,
                )

                total_inserted, batch_count = self._generate_and_insert_batches(
                    table_name, stream, count, batch_size, progress, gen_task
                )

            except (ValueError, RuntimeError, OSError, TypeError, AttributeError, KeyError, SQLAlchemyError) as e:
                if isinstance(e, SAIntegrityError) and enrich:
                    logger.warning("Integrity constraint during enrich", table_name=table_name, error=e)
                else:
                    logger.error("Failed to fill table", table_name=table_name, error=e)
                return GenerationResult(
                    table_name=table_name,
                    count=total_inserted,
                    elapsed=time.monotonic() - start_time,
                    errors=[str(e)],
                )
            finally:
                if self._optimize_pragma:
                    self._db.restore_settings()

        elapsed = time.monotonic() - start_time

        self._metrics.record(f"{table_name}.total_elapsed", elapsed)
        self._metrics.record(f"{table_name}.total_rows", float(total_inserted))

        self._plugins.hook.sqlseed_after_generate(
            table_name=table_name,
            count=total_inserted,
            elapsed=elapsed,
        )

        self._relation.register_shared_pool(table_name, generator_specs)
        self._plugins.hook.sqlseed_shared_pool_loaded(table_name=table_name, shared_pool=self._shared_pool)

        # Post-fill: update self-referencing FK columns to reference existing
        # rows, producing realistic hierarchical data (e.g., child orgs
        # referencing parent orgs). During initial bulk fill, self-ref FKs
        # are forced to null_ratio=1.0 (all NULL) because the table is empty.
        # This second pass updates ~70% of rows to reference already-generated
        # PK values, and adjusts conditional columns (e.g., org_type) to
        # satisfy bidirectional CHECK constraints.
        self._post_fill_self_ref_fks(table_name, generator_specs)

        return GenerationResult(
            table_name=table_name,
            count=total_inserted,
            elapsed=elapsed,
            batch_count=batch_count,
        )

    def _post_fill_self_ref_fks(
        self,
        table_name: str,
        generator_specs: dict[str, GeneratorSpec],
    ) -> None:
        """Post-fill: update self-referencing FK columns to reference existing rows.

        During initial bulk fill, self-referencing FK columns are forced to
        ``null_ratio=1.0`` (all NULL) because the table is empty. This second
        pass updates ~70% of rows to reference already-generated PK values,
        producing realistic hierarchical data (e.g., child orgs referencing
        parent orgs). For tables with bidirectional CHECK constraints linking
        the self-ref FK to a conditional column (e.g.,
        ``org_type = 'root' OR parent_id IS NOT NULL``), the conditional
        column is also updated to satisfy the CHECK constraint.

        This is a generic improvement for self-referencing FKs — a common
        pattern in real schemas (org hierarchies, category trees,
        manager-employee relationships). Without this pass, all self-ref FK
        values are NULL, producing unrealistic flat data.
        """
        fks = self._relation.get_foreign_keys(table_name)
        self_ref_fks = [fk for fk in fks if fk.ref_table == table_name]
        if not self_ref_fks:
            return

        pk_cols = self._db.get_primary_keys(table_name)
        if not pk_cols:
            return
        pk_col = pk_cols[0]

        pk_rows = self.query(
            f"SELECT {quote_identifier(pk_col)} AS pk "
            f"FROM {quote_identifier(table_name)} "
            f"ORDER BY {quote_identifier(pk_col)}"
        )
        if len(pk_rows) < 2:
            return
        pk_values = [r["pk"] for r in pk_rows]

        checks = self._db.get_check_constraints(table_name)
        # DBAPI placeholder: SQLite uses ?, PostgreSQL uses %s
        dialect = getattr(self._db, "dialect", None)
        ph = "%s" if dialect is not None and getattr(dialect, "name", "") == "postgresql" else "?"
        update_ratio = 0.7

        for fk in self_ref_fks:
            fk_col = fk.column
            spec = generator_specs.get(fk_col)
            if spec is None or spec.null_ratio < 1.0:
                continue

            cond_col, null_val = _detect_cond_column(fk_col, checks)
            non_null_values: list[str] = []
            if cond_col and null_val:
                non_null_values = _extract_non_null_values(cond_col, null_val, checks)
                if not non_null_values:
                    existing = self.query(
                        f"SELECT DISTINCT {quote_identifier(cond_col)} AS v "
                        f"FROM {quote_identifier(table_name)} "
                        f"WHERE {quote_identifier(cond_col)} IS NOT NULL "
                        f"AND {quote_identifier(cond_col)} != {ph}",
                        (null_val,),
                    )
                    non_null_values = [str(r["v"]) for r in existing]

            updated = 0
            for i, pk_val in enumerate(pk_values):
                if i == 0 or random.random() > update_ratio:
                    continue
                ref_pk = pk_values[random.randint(0, i - 1)]

                if cond_col and non_null_values:
                    new_cond = random.choice(non_null_values)
                    sql = (
                        f"UPDATE {quote_identifier(table_name)} "
                        f"SET {quote_identifier(fk_col)} = {ph}, "
                        f"{quote_identifier(cond_col)} = {ph} "
                        f"WHERE {quote_identifier(pk_col)} = {ph}"
                    )
                    try:
                        self.execute(sql, (ref_pk, new_cond, pk_val))
                        updated += 1
                    except SQLAlchemyError:
                        pass
                else:
                    sql = (
                        f"UPDATE {quote_identifier(table_name)} "
                        f"SET {quote_identifier(fk_col)} = {ph} "
                        f"WHERE {quote_identifier(pk_col)} = {ph}"
                    )
                    try:
                        self.execute(sql, (ref_pk, pk_val))
                        updated += 1
                    except SQLAlchemyError:
                        pass

            if updated:
                logger.info(
                    "Post-fill self-ref FK update",
                    table_name=table_name,
                    fk_col=fk_col,
                    updated=updated,
                    total=len(pk_values),
                )

    def preview_table(
        self,
        table_name: str,
        *,
        count: int = 5,
        columns: dict[str, Any] | None = None,
        seed: int | None = None,
        transform: str | None = None,
        column_configs: list[Any] | None = None,
        enrich: bool = False,
    ) -> list[dict[str, Any]]:
        """Generate preview rows without writing to the database.

        Resolves specs, builds a data stream, and applies plugin batch transforms
        (if any), returning up to ``count`` rows as dicts. No rows are persisted.
        """
        self._ensure_connected()
        validate_table_name(table_name)

        generator_specs, user_configs, unique_columns, composite_unique = self._resolve_specs(
            table_name, count, columns, column_configs, enrich
        )
        stream = self._build_stream(
            generator_specs,
            user_configs,
            unique_columns,
            transform,
            seed,
            table_name=table_name,
            composite_unique=composite_unique,
        )

        result: list[dict[str, Any]] = []
        for batch in stream.generate(count, batch_size=count):
            if self._plugin_mediator is not None:
                current_batch = self._plugin_mediator.apply_batch_transforms(table_name, batch)
            else:
                current_batch = batch
            result.extend(current_batch)
        return result

    fill = fill_table
