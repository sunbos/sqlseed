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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError as SAIntegrityError

from sqlseed._utils.logger import get_logger
from sqlseed._utils.progress import ProgressBackend, create_progress
from sqlseed._utils.sql_safe import quote_identifier, validate_table_name
from sqlseed.core.result import GenerationResult
from sqlseed.database._sqlite_schema import resolve_sqlite_table_name
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from sqlseed._utils.metrics import MetricsCollector
    from sqlseed.core.mapper import GeneratorSpec
    from sqlseed.core.plugin_mediator import PluginMediator
    from sqlseed.core.relation import RelationResolver, SharedPool
    from sqlseed.core.stream import DataStream
    from sqlseed.database._protocol import DatabaseAdapter, ForeignKeyInfo
    from sqlseed.plugins.manager import PluginManager

logger = get_logger(__name__)


@dataclass
class _CommittedBatches:
    """Counts acknowledged by successful adapter transactions, including partial fills."""

    rows: int = 0
    batches: int = 0


def _detect_cond_column(
    fk_col: str,
    checks: list[Any],
) -> tuple[str | None, str | int | None]:
    """Detect conditional column linked to self-ref FK via bidirectional CHECK.

    Looks for patterns like:
        cond_col = 'VALUE' OR fk_col IS NOT NULL  (string value)
        cond_col = NUMBER OR fk_col IS NOT NULL    (integer value)
        fk_col IS NOT NULL OR cond_col = 'VALUE'  (reversed, string)
        fk_col IS NOT NULL OR cond_col = NUMBER   (reversed, integer)

    Returns (cond_col, null_val) where null_val is the value cond_col must
    have when fk_col is NULL. Returns (None, None) if no pattern matches.
    """
    for check in checks:
        expr = check.expression
        # String: cond_col = 'VALUE' OR fk_col IS NOT NULL
        m = re.search(
            rf"(\w+)\s*=\s*'([^']+)'\s+OR\s+{re.escape(fk_col)}\s+IS\s+NOT\s+NULL",
            expr,
            re.IGNORECASE,
        )
        if m:
            return m.group(1), m.group(2)
        # Integer: cond_col = NUMBER OR fk_col IS NOT NULL
        m = re.search(
            rf"(\w+)\s*=\s*(\d+)\s+OR\s+{re.escape(fk_col)}\s+IS\s+NOT\s+NULL",
            expr,
            re.IGNORECASE,
        )
        if m:
            return m.group(1), int(m.group(2))
        # String: fk_col IS NOT NULL OR cond_col = 'VALUE'
        m = re.search(
            rf"{re.escape(fk_col)}\s+IS\s+NOT\s+NULL\s+OR\s+(\w+)\s*=\s*'([^']+)'",
            expr,
            re.IGNORECASE,
        )
        if m:
            return m.group(1), m.group(2)
        # Integer: fk_col IS NOT NULL OR cond_col = NUMBER
        m = re.search(
            rf"{re.escape(fk_col)}\s+IS\s+NOT\s+NULL\s+OR\s+(\w+)\s*=\s*(\d+)",
            expr,
            re.IGNORECASE,
        )
        if m:
            return m.group(1), int(m.group(2))
    return None, None


def _extract_non_null_values(
    cond_col: str,
    null_val: str | int,
    checks: list[Any],
) -> list[str | int]:
    """Extract valid non-null values for cond_col from IN constraint.

    Looks for ``cond_col IN ('V1', 'V2', ...)`` (string) or
    ``cond_col IN (1, 2, 3, ...)`` (integer) and returns the values
    excluding ``null_val``.
    """
    for check in checks:
        m = re.search(
            rf"{re.escape(cond_col)}\s+IN\s*\(([^)]+)\)",
            check.expression,
            re.IGNORECASE,
        )
        if m:
            raw = m.group(1)
            # Try string values first: 'V1', 'V2', ...
            values: list[str | int]
            if not (values := re.findall(r"'([^']+)'", raw)):
                # No string values found — try integer values: 1, 2, 3, ...
                values = [int(v) for v in re.findall(r"\b(\d+)\b", raw)]
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
        committed: _CommittedBatches | None = None,
    ) -> tuple[int, int]:
        """Generate and write data batch by batch, triggering before/after_insert plugin hooks.

        Each batch executes in order: sqlseed_before_insert hook, PluginMediator batch transform,
        batch_insert write, metrics recording, sqlseed_after_insert hook, progress update.
        When progress is not passed in, an internal progress bar is created and its lifecycle managed.

        Args:
            table_name: Target table name.
            stream: Data stream, producing dict rows per batch.
            count: Total number of rows to generate.
            batch_size: Maximum number of generated rows held per batch.
            progress: Optional progress bar instance; created internally when None.
            task_id: Optional progress task ID; added internally when None.
            committed: Optional shared counter of completed writes, updated before post-insert hooks.

        Returns:
            A tuple (total_inserted, batch_count).
        """
        total_inserted = 0
        batch_count = 0
        effective_batch_size = min(batch_size, count)
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
                if committed is not None:
                    committed.rows += inserted
                    committed.batches += 1

                self._metrics.record(f"{table_name}.batch_insert", float(inserted))

                self._plugins.hook.sqlseed_after_insert(
                    table_name=table_name,
                    batch_number=batch_count,
                    rows_inserted=inserted,
                )

                progress.update(task_id, advance=len(batch))
        return total_inserted, batch_count

    def _preflight_generation(self, table_names: list[str]) -> dict[str, str]:
        """Validate all schemas before writing and return their catalog names."""
        self._ensure_connected()
        for table_name in table_names:
            validate_table_name(table_name)
        existing_tables = self._db.get_table_names()
        dialect = getattr(self._db, "dialect", None)
        is_sqlite = dialect is None or dialect.name == "sqlite"
        resolved: dict[str, str] = {}
        for table_name in table_names:
            canonical = resolve_sqlite_table_name(table_name, existing_tables) if is_sqlite else table_name
            if canonical not in existing_tables:
                raise RuntimeError(f"Table '{table_name}' does not exist")
            resolved[table_name] = canonical
            if not is_sqlite:
                # CHECK inference currently matches SQLite identifiers. PG
                # allows quoted columns such as "A" and "a" to coexist, so
                # reject that ambiguity before any requested table is cleared.
                ascii_fold = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
                names = [column.name.translate(ascii_fold) for column in self._db.get_column_info(canonical)]
                if len(names) != len(set(names)):
                    raise ConfigurationError(
                        f"Table '{canonical}': PostgreSQL columns differing only by ASCII case are not supported "
                        "for generation. Use distinct column names. No rows were changed by this preflight."
                    )
            self._relation.validate_generation_schema(canonical)
        return resolved

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
        progress: ProgressBackend | None = None,
    ) -> GenerationResult:
        """Batch-generate and write test data to the specified table, returning the generation result.

        Full flow: connection init -> table name validation -> pragma optimization ->
        spec preparation (_prepare_specs) -> data stream build (_build_stream) ->
        batch generation & write (_generate_and_insert_batches) -> shared pool registration ->
        hook notification. Operational failures, including expression and post-fill
        errors, return a GenerationResult with an errors field. Process-control
        exceptions, argument validation failures and ConfigurationError still propagate.

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
            progress: Optional caller-managed backend. None creates and closes the default backend.

        Returns:
            GenerationResult containing table_name, count, elapsed, batch_count;
            on failure the errors field carries exception info.
        """
        self._ensure_connected()
        validate_table_name(table_name)
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if count <= 0:
            raise ValueError(f"count must be greater than 0, got {count}")
        start_time = time.monotonic()
        total_inserted = 0
        batch_count = 0

        committed = _CommittedBatches()
        try:
            table_name = self._preflight_generation([table_name])[table_name]
            own_progress = progress is None
            if progress is None:
                progress = create_progress()
            with contextlib.ExitStack() as stack:
                if own_progress:
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
                        table_name, stream, count, batch_size, progress, gen_task, committed
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
            self._post_fill_self_ref_fks(table_name, generator_specs, seed=seed)

            return GenerationResult(
                table_name=table_name,
                count=total_inserted,
                elapsed=elapsed,
                batch_count=batch_count,
            )
        except ConfigurationError:
            raise
        except Exception as e:
            self._log_fill_failure(table_name, e, enrich)
            return GenerationResult(
                table_name=table_name,
                count=committed.rows,
                elapsed=time.monotonic() - start_time,
                batch_count=committed.batches,
                errors=[str(e)],
            )

    @staticmethod
    def _log_fill_failure(table_name: str, error: Exception, enrich: bool) -> None:
        """Keep enrichment integrity failures distinct from other operational failures."""
        if isinstance(error, SAIntegrityError) and enrich:
            logger.warning("Integrity constraint during enrich", table_name=table_name, error=error)
        else:
            logger.error("Failed to fill table", table_name=table_name, error=error)

    def _post_fill_self_ref_fks(
        self,
        table_name: str,
        generator_specs: dict[str, GeneratorSpec],
        *,
        seed: int | None = None,
    ) -> None:
        """Post-fill: update self-referencing FK columns to reference existing rows.

        Only columns marked as automatically deferred while the table was
        empty qualify; explicit all-NULL requests and append fills do not.
        During initial bulk fill, these columns are forced to
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
        if not (self_ref_fks := [fk for fk in fks if fk.ref_table == table_name]):
            return

        if not (pk_cols := self._db.get_primary_keys(table_name)):
            return
        pk_col = pk_cols[0]

        checks = self._db.get_check_constraints(table_name)
        # DBAPI placeholder: SQLite uses ?, PostgreSQL uses %s
        dialect = getattr(self._db, "dialect", None)
        ph = "%s" if dialect is not None and getattr(dialect, "name", "") == "postgresql" else "?"
        # Keep seeded fills reproducible without reseeding the provider or the
        # process-wide RNG. Unseeded fills retain their existing random source.
        rng = random.Random(seed) if seed is not None else random

        for fk in self_ref_fks:
            fk_col = fk.column
            spec = generator_specs.get(fk_col)
            if spec is None or not spec.params.get("_self_ref_deferred"):
                continue
            self._update_self_ref_column(table_name, pk_col, fk, checks, ph, rng)

    def _self_ref_condition_values(
        self, table_name: str, fk_col: str, checks: list[Any], ph: str
    ) -> tuple[str | None, list[str | int]]:
        """Find allowed condition values, using existing rows when CHECK has no enum."""
        cond_col, null_val = _detect_cond_column(fk_col, checks)
        non_null_values: list[str | int] = []
        if (
            cond_col
            and null_val is not None
            and not (non_null_values := _extract_non_null_values(cond_col, null_val, checks))
        ):
            existing = self.query(
                f"SELECT DISTINCT {quote_identifier(cond_col)} AS v "
                f"FROM {quote_identifier(table_name)} "
                f"WHERE {quote_identifier(cond_col)} IS NOT NULL "
                f"AND {quote_identifier(cond_col)} != {ph}",
                (null_val,),
            )
            # Preserve the CHECK literal type in values sampled for UPDATE.
            if isinstance(null_val, int):
                non_null_values = [int(r["v"]) for r in existing]
            else:
                non_null_values = [str(r["v"]) for r in existing]
        return cond_col, non_null_values

    def _update_self_ref_column(
        self,
        table_name: str,
        pk_col: str,
        fk: ForeignKeyInfo,
        checks: list[Any],
        ph: str,
        rng: random.Random | ModuleType,
    ) -> None:
        """Link one deferred FK to preceding rows using the fill's existing RNG."""
        fk_col = fk.column
        pk_rows = self.query(
            f"SELECT {quote_identifier(pk_col)} AS pk, "
            f"{quote_identifier(fk.ref_column)} AS ref_value "
            f"FROM {quote_identifier(table_name)} "
            f"ORDER BY {quote_identifier(pk_col)}"
        )
        if len(pk_rows) < 2:
            return
        pk_values = [row["pk"] for row in pk_rows]
        ref_values = [row["ref_value"] for row in pk_rows]
        cond_col, non_null_values = self._self_ref_condition_values(table_name, fk_col, checks, ph)

        updated = 0
        for i, pk_val in enumerate(pk_values):
            if i == 0 or rng.random() > 0.7:
                continue
            if (ref_value := ref_values[rng.randint(0, i - 1)]) is None:
                continue

            if cond_col and non_null_values:
                new_cond = rng.choice(non_null_values)
                sql = (
                    f"UPDATE {quote_identifier(table_name)} "
                    f"SET {quote_identifier(fk_col)} = {ph}, "
                    f"{quote_identifier(cond_col)} = {ph} "
                    f"WHERE {quote_identifier(pk_col)} = {ph}"
                )
                self.execute(sql, (ref_value, new_cond, pk_val)).close()
                updated += 1
            else:
                sql = (
                    f"UPDATE {quote_identifier(table_name)} "
                    f"SET {quote_identifier(fk_col)} = {ph} "
                    f"WHERE {quote_identifier(pk_col)} = {ph}"
                )
                self.execute(sql, (ref_value, pk_val)).close()
                updated += 1

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

        table_name = self._preflight_generation([table_name])[table_name]
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
