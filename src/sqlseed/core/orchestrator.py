"""Data orchestration engine, coordinating schema inference, column mapping, relation resolution,
constraint solving, enrichment, and database writes.

DataOrchestrator serves as the core entry point, wiring together SchemaInferrer,
ColumnMapper, RelationResolver, ConstraintSolver, EnrichmentEngine and other components
to complete the full flow from schema inference to batch data writes. Production
environments uniformly use SQLAlchemyAdapter, and all database exceptions are of
sqlalchemy.exc.* types.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.exc import OperationalError as SAOperationalError

from sqlseed._utils.logger import get_logger
from sqlseed._utils.metrics import MetricsCollector
from sqlseed._utils.progress import ProgressBackend, create_progress
from sqlseed._utils.sql_safe import validate_table_name
from sqlseed.config.models import ColumnConfig
from sqlseed.core.column_dag import ColumnDAG
from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.enrichment import EnrichmentEngine
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.mapper import ColumnMapper
from sqlseed.core.plugin_mediator import PluginMediator
from sqlseed.core.relation import RelationResolver, SharedPool
from sqlseed.core.result import GenerationResult
from sqlseed.core.schema import SchemaInferrer
from sqlseed.core.transform import load_transform
from sqlseed.core.unique_adjuster import UniqueAdjuster
from sqlseed.generators.registry import ProviderRegistry
from sqlseed.generators.stream import DataStream
from sqlseed.plugins.manager import PluginManager

if TYPE_CHECKING:
    from sqlseed.database._protocol import DatabaseAdapter

logger = get_logger(__name__)


def _is_db_url(target: str) -> bool:
    """Determine whether the connection target is a database URL (with scheme) or a plain file path.

    URL examples: "postgresql://user:pass@host/db", "mysql+pymysql://..."
    File path examples: "/path/to/db.sqlite", "app.db"

    A SQLAlchemy URL must contain "://" (the scheme + authority/path separator).
    """
    return "://" in target


@dataclass
class CoreCtx:
    db: DatabaseAdapter | None = None
    schema: SchemaInferrer | None = None
    mapper: ColumnMapper = field(default_factory=ColumnMapper)
    relation: RelationResolver | None = None
    shared_pool: SharedPool = field(default_factory=SharedPool)


@dataclass
class ExtCtx:
    registry: ProviderRegistry = field(default_factory=ProviderRegistry)
    plugins: PluginManager = field(default_factory=PluginManager)
    plugin_mediator: PluginMediator | None = None
    enrichment: EnrichmentEngine | None = None
    unique_adjuster: UniqueAdjuster | None = None
    metrics: MetricsCollector = field(default_factory=MetricsCollector)


class DataOrchestrator:
    """Data orchestration engine, wiring together schema inference, column mapping,
    relation resolution, and batch writes.

    Manages core components (schema, mapper, relation) and extension components
    (registry, plugins, enrichment) via two context groups CoreCtx/ExtCtx.
    Supports the context manager protocol to ensure controllable connection lifecycle.
    Production environments uniformly use SQLAlchemyAdapter to shield multi-database dialect differences.
    """

    def __init__(
        self,
        db_path: str,
        *,
        provider_name: str = "mimesis",
        locale: str = "en_US",
        optimize_pragma: bool = True,
        associations: list[Any] | None = None,
    ) -> None:
        self._db_path = db_path
        self._provider_name = provider_name
        self._locale = locale
        self._optimize_pragma = optimize_pragma

        db_adapter = self._create_adapter()
        shared_pool = SharedPool()
        self._core = CoreCtx(
            db=db_adapter,
            schema=SchemaInferrer(db_adapter),
            relation=RelationResolver(db_adapter, shared_pool),
            shared_pool=shared_pool,
        )
        self._ext = ExtCtx(unique_adjuster=UniqueAdjuster(self._core.mapper))
        self._connected = False

        if associations:
            self._relation.set_associations(associations)

    @property
    def _db(self) -> DatabaseAdapter:
        if self._core.db is None:
            raise RuntimeError("Database adapter not initialized. Call _ensure_connected() first.")
        return self._core.db

    @property
    def _schema(self) -> SchemaInferrer:
        if self._core.schema is None:
            raise RuntimeError("SchemaInferrer not initialized. Call _ensure_connected() first.")
        return self._core.schema

    @property
    def _mapper(self) -> ColumnMapper:
        return self._core.mapper

    @property
    def _relation(self) -> RelationResolver:
        rel = self._core.relation
        if rel is None:
            raise RuntimeError("RelationResolver not initialized. Call _ensure_connected() first.")
        return rel

    @property
    def _shared_pool(self) -> SharedPool:
        return self._core.shared_pool

    @property
    def _registry(self) -> ProviderRegistry:
        return self._ext.registry

    @property
    def _plugins(self) -> PluginManager:
        return self._ext.plugins

    @property
    def _plugin_mediator(self) -> PluginMediator | None:
        return self._ext.plugin_mediator

    @_plugin_mediator.setter
    def _plugin_mediator(self, v: PluginMediator | None) -> None:
        self._ext.plugin_mediator = v

    @property
    def _enrichment(self) -> EnrichmentEngine | None:
        return self._ext.enrichment

    @_enrichment.setter
    def _enrichment(self, v: EnrichmentEngine | None) -> None:
        self._ext.enrichment = v

    @property
    def _unique_adjuster(self) -> UniqueAdjuster:
        adj = self._ext.unique_adjuster
        if adj is None:
            raise RuntimeError("UniqueAdjuster not initialized. Call _ensure_connected() first.")
        return adj

    @property
    def _metrics(self) -> MetricsCollector:
        return self._ext.metrics

    @classmethod
    def from_config(cls, config: Any) -> DataOrchestrator:
        return cls(
            db_path=config.connection_target,
            provider_name=config.provider.value,
            locale=config.locale,
            optimize_pragma=config.optimize_pragma,
            associations=config.associations if config.associations else None,
        )

    def _create_adapter(self) -> DatabaseAdapter:
        # Phase 4: uniformly use SQLAlchemyAdapter (SQLAlchemy is a core dependency).
        # SQLAlchemyAdapter automatically handles database URLs (postgresql://, mysql://, etc.)
        # and SQLite file paths, shielding dialect differences via the Dialect abstraction.
        from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter  # noqa: PLC0415

        if _is_db_url(self._db_path):
            logger.debug("Using SQLAlchemyAdapter (database URL)", db_target=self._db_path)
        else:
            logger.debug("Using SQLAlchemyAdapter (SQLite file)", db_target=self._db_path)
        return SQLAlchemyAdapter()

    def _ensure_connected(self) -> None:
        if not self._connected:
            self._db.connect(self._db_path)
            self._connected = True
            self._enrichment = EnrichmentEngine(self._db, self._mapper, self._schema)
            self._plugins.load_plugins()
            self._plugins.hook.sqlseed_register_providers(registry=self._registry)
            self._plugins.hook.sqlseed_register_column_mappers(mapper=self._mapper)
            self._registry.register_from_entry_points()
            try:
                self._registry.ensure_provider(self._provider_name)
                self._registry.set_default(self._provider_name)
            except (ImportError, ValueError):
                logger.warning(
                    "Provider not available, falling back to 'base'",
                    provider_name=self._provider_name,
                )
                self._provider_name = "base"
            provider = self._registry.get(self._provider_name)
            provider.set_locale(self._locale)
            self._plugin_mediator = PluginMediator(self._plugins, self._db, self._schema)

    def _resolve_specs(
        self,
        table_name: str,
        count: int,
        columns: dict[str, Any] | None,
        column_configs: list[Any] | None,
        enrich: bool,
    ) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
        """Resolve column generator specs, executing schema inference, column mapping, enrichment,
        uniqueness adjustment, and foreign key resolution in order.

        Args:
            table_name: Target table name.
            count: Number of rows to generate, used to compute the value space during uniqueness adjustment.
            columns: Simple column config dict (column name -> string/dict).
            column_configs: List of ColumnConfig objects (full column config).
            enrich: Whether to enable enrichment mode (identify enumeration columns based on existing data).

        Returns:
            A triple (generator_specs, user_configs, unique_columns).
        """
        column_infos = self._schema.get_column_info(table_name)
        user_configs = self._resolve_user_configs(columns, column_configs)
        generator_specs = self._mapper.map_columns(column_infos, user_configs, enrich=enrich)
        unique_columns = self._schema.detect_unique_columns(table_name)
        if self._enrichment is not None:
            generator_specs = self._enrichment.apply(table_name, generator_specs, column_infos, unique_columns)
        generator_specs = self._unique_adjuster.adjust(generator_specs, unique_columns, count, column_infos)
        generator_specs = self._relation.resolve_foreign_keys(
            table_name,
            generator_specs,
            unique_columns=unique_columns,
        )
        return generator_specs, user_configs, unique_columns

    def _build_stream(
        self,
        generator_specs: dict[str, Any],
        user_configs: dict[str, Any],
        unique_columns: set[str],
        transform: str | None,
        seed: int | None,
    ) -> DataStream:
        dag = ColumnDAG()
        col_configs_list = list(user_configs.values()) if user_configs else None
        dag_nodes = dag.build(generator_specs, col_configs_list, unique_columns=unique_columns)

        expr_engine = ExpressionEngine()
        constraint_solver = ConstraintSolver()

        transform_fn = None
        if transform:
            transform_fn = load_transform(transform)

        provider = self._registry.get(self._provider_name)

        return DataStream(
            dag_nodes=dag_nodes,
            provider=provider,
            expr_engine=expr_engine,
            constraint_solver=constraint_solver,
            transform_fn=transform_fn,
            seed=seed,
        )

    def _prepare_specs(
        self,
        table_name: str,
        count: int,
        columns: dict[str, Any] | None,
        column_configs: list[Any] | None,
        enrich: bool,
        clear_before: bool,
        skip_ai: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
        """Prepare generator specs, handling the execution order of clear_before and enrich,
        and apply AI suggestions and template pool.

        Execution order rules:
            - enrich and clear_before: resolve specs first (enrich based on existing data), then clear the table
            - clear_before only: clear the table first, then resolve specs
            - Otherwise: resolve specs directly

        When skip_ai=False, calls PluginMediator to apply AI column suggestions and template pool enrichment.

        Args:
            table_name: Target table name.
            count: Number of rows to generate.
            columns: Simple column config dict (optional).
            column_configs: List of ColumnConfig objects (optional).
            enrich: Whether to enable enrichment mode.
            clear_before: Whether to clear the table before generation.
            skip_ai: Whether to skip AI suggestions and template pool application.

        Returns:
            A triple (generator_specs, user_configs, unique_columns).
        """
        t_resolve = time.monotonic()
        if enrich and clear_before:
            specs, user_configs, unique_columns = self._resolve_specs(
                table_name, count, columns, column_configs, enrich
            )
            self._db.clear_table(table_name)
        else:
            if clear_before:
                self._db.clear_table(table_name)
            specs, user_configs, unique_columns = self._resolve_specs(
                table_name, count, columns, column_configs, enrich
            )
        logger.debug("resolve_specs", table_name=table_name, elapsed=f"{time.monotonic() - t_resolve:.3f}s")
        builtin_count = sum(
            1 for s in specs.values() if s.generator_name not in {"string", "skip", "__enrich__", "__derive__"}
        )
        string_count = sum(1 for s in specs.values() if s.generator_name == "string")
        logger.info(
            "Column mapping resolved",
            table_name=table_name,
            builtin_matched=builtin_count,
            string_fallback=string_count,
        )
        if self._plugin_mediator is not None and not skip_ai:
            column_infos = self._schema.get_column_info(table_name)
            user_configured = {uc.name for uc in user_configs if hasattr(uc, "name")}
            t_ai = time.monotonic()
            specs = self._plugin_mediator.apply_ai_suggestions(
                table_name,
                column_infos,
                specs,
                user_configured_columns=user_configured,
            )
            logger.debug("ai_suggestions", table_name=table_name, elapsed=f"{time.monotonic() - t_ai:.3f}s")
            t_tpl = time.monotonic()
            specs = self._plugin_mediator.apply_template_pool(
                table_name,
                column_infos,
                specs,
                count,
                user_configured_columns=user_configured,
                unique_columns=unique_columns,
            )
            logger.debug("template_pool", table_name=table_name, elapsed=f"{time.monotonic() - t_tpl:.3f}s")
        return specs, user_configs, unique_columns

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
            desired_batches = max(10, count // effective_batch_size)
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
                generator_specs, user_configs, unique_columns = self._prepare_specs(
                    table_name, count, columns, column_configs, enrich, clear_before, skip_ai
                )

                progress.update(prep_task, description=f"Building data stream for {table_name}...")
                stream = self._build_stream(generator_specs, user_configs, unique_columns, transform, seed)

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

            except (ValueError, RuntimeError, OSError, SAOperationalError, SAIntegrityError) as e:
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

        return GenerationResult(
            table_name=table_name,
            count=total_inserted,
            elapsed=elapsed,
            batch_count=batch_count,
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
        self._ensure_connected()
        validate_table_name(table_name)

        generator_specs, user_configs, unique_columns = self._resolve_specs(
            table_name, count, columns, column_configs, enrich
        )
        stream = self._build_stream(generator_specs, user_configs, unique_columns, transform, seed)

        result: list[dict[str, Any]] = []
        for batch in stream.generate(count, batch_size=count):
            if self._plugin_mediator is not None:
                current_batch = self._plugin_mediator.apply_batch_transforms(table_name, batch)
            else:
                current_batch = batch
            result.extend(current_batch)
        return result

    def get_schema_context(self, table_name: str) -> dict[str, Any]:
        self._ensure_connected()
        validate_table_name(table_name)
        column_infos = self._schema.get_column_info(table_name)
        fks = self._db.get_foreign_keys(table_name)
        all_tables = self._db.get_table_names()

        indexes: list[dict[str, Any]] = []
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            idx_infos = self._schema.get_index_info(table_name)
            indexes = [{"name": idx.name, "columns": idx.columns, "unique": idx.unique} for idx in idx_infos]

        sample_data: list[dict[str, Any]] = []
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            sample_data = self._schema.get_sample_data(table_name, limit=5)

        distribution: list[dict[str, Any]] = []
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            distribution = self._schema.profile_column_distribution(table_name, limit=1000)

        return {
            "table_name": table_name,
            "columns": column_infos,
            "foreign_keys": fks,
            "indexes": indexes,
            "sample_data": sample_data,
            "all_table_names": all_tables,
            "distribution": distribution,
            "dialect": self._get_dialect_name(),
        }

    def _get_dialect_name(self) -> str:
        """Get the current database dialect name (sqlite/postgresql/mysql), used for AI analysis context.

        If the adapter does not expose a dialect attribute (e.g., RawSQLiteAdapter), defaults to "sqlite".
        """
        db = self._core.db
        if db is not None and hasattr(db, "dialect"):
            try:
                return str(db.dialect.name)
            except RuntimeError:
                pass
        return "sqlite"

    def get_column_names(self, table_name: str) -> set[str]:
        self._ensure_connected()
        return {c.name for c in self._schema.get_column_info(table_name)}

    def get_skippable_columns(self, table_name: str) -> set[str]:
        self._ensure_connected()
        return {
            c.name
            for c in self._schema.get_column_info(table_name)
            if (c.is_primary_key and c.is_autoincrement) or c.default is not None
        }

    def get_topological_table_order(self, table_names: list[str]) -> list[str]:
        self._ensure_connected()
        return self._relation.topological_sort(table_names)

    def get_table_names(self) -> list[str]:
        self._ensure_connected()
        return self._db.get_table_names()

    def get_column_info(self, table_name: str) -> list[Any]:
        self._ensure_connected()
        return self._schema.get_column_info(table_name)

    def get_foreign_keys(self, table_name: str) -> list[Any]:
        self._ensure_connected()
        return self._db.get_foreign_keys(table_name)

    def get_row_count(self, table_name: str) -> int:
        self._ensure_connected()
        return self._db.get_row_count(table_name)

    def map_column(self, column_info: Any) -> Any:
        return self._mapper.map_column(column_info)

    def report(self) -> str:
        if not self._connected:
            return "Not connected to any database."

        tables = self._db.get_table_names()
        lines = [f"Database: {self._db_path}", "=" * 50]
        for table in tables:
            count = self._db.get_row_count(table)
            lines.append(f"  {table}: {count} rows")
        return "\n".join(lines)

    def _resolve_user_configs(
        self,
        columns: dict[str, Any] | None,
        column_configs: list[Any] | None,
    ) -> dict[str, Any]:
        configs: dict[str, Any] = {}

        if column_configs:
            for cc in column_configs:
                if isinstance(cc, ColumnConfig):
                    configs[cc.name] = cc

        if columns:
            for col_name, col_spec in columns.items():
                if isinstance(col_spec, str):
                    configs[col_name] = ColumnConfig(name=col_name, generator=col_spec)
                elif isinstance(col_spec, dict):
                    configs[col_name] = ColumnConfig(name=col_name, **col_spec)

        return configs

    fill = fill_table

    def get_column_mapping(self, table_name: str) -> dict[str, Any]:
        """Get column-to-generator mapping for diagnostic display.

        This is the public API for the ``inspect --show-mapping`` CLI command.
        Returns the generator specs dict keyed by column name.
        """
        self._ensure_connected()
        specs, _, _ = self._resolve_specs(
            table_name,
            count=1,
            columns=None,
            column_configs=None,
            enrich=False,
        )
        return specs

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> Any:
        """Execute a SQL statement.

        Args:
            sql: The SQL statement to execute.
            params: Optional tuple of parameters for parameterized queries.

        Returns:
            A cursor object with the result.
        """
        self._ensure_connected()
        if params is None:
            params = ()
        return self._db.execute(sql, params)

    def query(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        """Execute a SELECT query and return results as a list of dictionaries.

        Args:
            sql: The SQL SELECT query to execute.
            params: Optional tuple of parameters for parameterized queries.

        Returns:
            A list of dictionaries, where each dictionary represents a row.
        """
        self._ensure_connected()
        cursor = self.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        """Execute a SELECT query and return a single row as a dictionary.

        Args:
            sql: The SQL SELECT query to execute.
            params: Optional tuple of parameters for parameterized queries.

        Returns:
            A dictionary representing the first row, or None if no rows found.
        """
        self._ensure_connected()
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row, strict=True))

    def close(self) -> None:
        if self._connected:
            self._db.close()
            self._connected = False

    def __enter__(self) -> DataOrchestrator:
        self._ensure_connected()
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> None:
        self.close()
