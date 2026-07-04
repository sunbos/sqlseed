"""Spec resolver mixin: column spec resolution, stream building, and AI/template application.

Separated from the original ``orchestrator.py`` to isolate the concerns of
generator spec preparation (schema inference, column mapping, enrichment,
uniqueness adjustment, foreign key resolution), data stream construction,
and AI suggestion / template pool application.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed.config.models import ColumnConfig
from sqlseed.core.column_dag import ColumnDAG
from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.stream import DataStream
from sqlseed.core.transform import load_transform

if TYPE_CHECKING:
    from sqlseed.core.enrichment import EnrichmentEngine
    from sqlseed.core.mapper import ColumnMapper
    from sqlseed.core.plugin_mediator import PluginMediator
    from sqlseed.core.relation import RelationResolver
    from sqlseed.core.schema import SchemaInferrer
    from sqlseed.core.schema_fallback import SchemaFallbackGenerator
    from sqlseed.core.unique_adjuster import UniqueAdjuster
    from sqlseed.database._protocol import DatabaseAdapter
    from sqlseed.generators.registry import ProviderRegistry
    from sqlseed.plugins.manager import PluginManager

logger = get_logger(__name__)


class SpecResolverMixin:
    """Mixin providing generator spec resolution and data stream construction.

    Owns ``_resolve_specs``, ``_build_stream``, ``_prepare_specs``, and
    ``_resolve_user_configs``. Expects the host class to expose the
    ``ConnectionMixin`` accessors (``_schema``, ``_mapper``, ``_enrichment``,
    ``_unique_adjuster``, ``_relation``, ``_registry``, ``_db``,
    ``_plugin_mediator``, ``_provider_name``).
    """

    # Instance attribute provided by ConnectionMixin.
    _provider_name: str

    if TYPE_CHECKING:
        # Provided by ConnectionMixin as read-only properties. Split into two
        # TYPE_CHECKING blocks to keep each block's McCabe complexity under
        # pylint's too-complex threshold (10). The first block groups the
        # Connection/registry accessors; the second groups the enrichment/
        # unique-adjuster accessors.
        @property
        def _db(self) -> DatabaseAdapter:
            raise NotImplementedError

        @property
        def _schema(self) -> SchemaInferrer:
            raise NotImplementedError

        @property
        def _mapper(self) -> ColumnMapper:
            raise NotImplementedError

        @property
        def _relation(self) -> RelationResolver:
            raise NotImplementedError

        @property
        def _registry(self) -> ProviderRegistry:
            raise NotImplementedError

    if TYPE_CHECKING:

        @property
        def _plugins(self) -> PluginManager:
            raise NotImplementedError

        @property
        def _plugin_mediator(self) -> PluginMediator | None:
            raise NotImplementedError

        @property
        def _enrichment(self) -> EnrichmentEngine | None:
            raise NotImplementedError

        @property
        def _unique_adjuster(self) -> UniqueAdjuster:
            raise NotImplementedError

        @property
        def _schema_fallback(self) -> SchemaFallbackGenerator | None:
            raise NotImplementedError

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
        # L9+ enhancement: SchemaFallbackGenerator adds CHECK-constraint and
        # UNIQUE-aware params to columns that fell through to L9 type-fallback
        # (generator_name == "string"). Skips columns with user_config (user
        # intent wins) and L1-L8 name-matched columns (business hints win).
        if self._schema_fallback is not None:
            check_constraints = self._db.get_check_constraints(table_name)
            unique_list = list(unique_columns)
            for col_info in column_infos:
                col_name = col_info.name
                if col_name in user_configs:
                    continue
                current_spec = generator_specs.get(col_name)
                if current_spec is None:
                    continue
                if current_spec.generator_name != "string":
                    continue
                enhanced = self._schema_fallback.fallback_for_column(col_info, check_constraints, unique_list)
                if enhanced is not None:
                    generator_specs[col_name] = enhanced
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

        expr_engine = ExpressionEngine(db_adapter=self._db)
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
            # user_configs is a dict[str, ColumnConfig]; iterate .values() so that
            # hasattr(uc, "name") is evaluated on ColumnConfig objects (not dict keys).
            user_configured = {uc.name for uc in user_configs.values() if hasattr(uc, "name")}
            t_ai = time.monotonic()
            # AI suggestion mediation lives in sqlseed-ai (per ARCHITECTURE.md
            # Section 7.6). The orchestrator invokes it via the high-level
            # ``sqlseed_apply_ai_suggestions`` pluggy hook — when no AI plugin
            # is installed, pluggy returns None and we keep ``specs`` unchanged.
            ai_specs = self._plugins.hook.sqlseed_apply_ai_suggestions(
                table_name=table_name,
                column_infos=column_infos,
                specs=specs,
                user_configured_columns=user_configured,
                db=self._db,
                schema=self._schema,
            )
            if ai_specs is not None:
                specs = ai_specs
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
