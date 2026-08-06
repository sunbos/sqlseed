"""Spec resolver mixin: column spec resolution, stream building, and AI/template application.

Separated from the original ``orchestrator.py`` to isolate the concerns of
generator spec preparation (schema inference, column mapping, enrichment,
uniqueness adjustment, foreign key resolution), data stream construction,
and AI suggestion / template pool application.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed.config.models import ColumnConfig
from sqlseed.core.check_adapt import CheckAdapter
from sqlseed.core.check_parser import CheckConstraintParser
from sqlseed.core.column_dag import ColumnDAG
from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.mapper import GeneratorSpec
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
    _locale: str

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
    ) -> tuple[dict[str, Any], dict[str, Any], set[str], list[list[str]]]:
        """Resolve column generator specs, executing schema inference, column mapping, enrichment,
        uniqueness adjustment, and foreign key resolution in order.

        Args:
            table_name: Target table name.
            count: Number of rows to generate, used to compute the value space during uniqueness adjustment.
            columns: Simple column config dict (column name -> string/dict).
            column_configs: List of ColumnConfig objects (full column config).
            enrich: Whether to enable enrichment mode (identify enumeration columns based on existing data).

        Returns:
            A 4-tuple (generator_specs, user_configs, unique_columns, composite_unique).
            ``composite_unique`` is a list of column-name lists, each representing
            one composite UNIQUE constraint (e.g., ``UNIQUE(a, b)`` → ``[['a', 'b']]``).
        """
        column_infos = self._schema.get_column_info(table_name)
        user_configs = self._resolve_user_configs(columns, column_configs)
        check_constraints = self._db.get_check_constraints(table_name)
        # CHECK-constraint adaptation: deterministically clamp user-supplied YAML
        # value domains (params.min_value/max_value/choices/min_length/max_length)
        # against the column's CHECK constraint so generated data always satisfies
        # it. Overlapping domains are clamped (with a notice); disjoint domains
        # raise ConfigurationError. Skipped for derived columns and for CHECKs the
        # parser cannot deterministically resolve (cross-column/OR/column refs —
        # those stay the AI/manual domain). Runs before map_columns so the clamped
        # params flow into the GeneratorSpec.
        if user_configs:
            if check_constraints:
                adapter = CheckAdapter(locale=self._locale)
                adapter.adapt_user_configs(
                    user_configs,
                    [ck.expression for ck in check_constraints],
                )
        elif check_constraints:
            # Zero-config path (no columns/column_configs): type-driven mapping only.
            # Honestly declare that this mode does NOT guarantee CHECK-constraint
            # compliance — generated values follow column types, not business rules.
            # Point the user to the layered workflow: AI analysis (ai-analyze) or
            # hand-written YAML for business-compliant data. This is a capability
            # boundary declaration, not a fix attempt.
            self._declare_zero_config_check_boundary(table_name, check_constraints)
        generator_specs = self._mapper.map_columns(column_infos, user_configs, enrich=enrich)
        unique_columns = self._schema.detect_unique_columns(table_name)
        composite_unique = self._schema.detect_composite_unique_constraints(table_name)
        if self._enrichment is not None:
            generator_specs = self._enrichment.apply(table_name, generator_specs, column_infos, unique_columns)
        # L9+ enhancement: SchemaFallbackGenerator adds CHECK-constraint and
        # UNIQUE-aware params to columns that fell through to L9 type-fallback
        # (generator_name in _TYPE_FALLBACK_GENERATORS). Skips columns with
        # user_config (user intent wins) and L1-L8 name-matched columns
        # (business hints win). Also applies to "choice" columns whose params
        # are empty (e.g., when EXACT_MATCH_RULES mapped to "choice" but no
        # choices were provided in EXACT_MATCH_PARAMS) so CHECK-derived enums
        # can fill the gap.
        if self._schema_fallback is not None:
            check_constraints = self._db.get_check_constraints(table_name)
            unique_list = list(unique_columns)
            # Generators produced by L9 type-fallback that may benefit from
            # CHECK constraint inference (range, length, choices).
            _fallback_generators = {"string", "integer", "float", "boolean", "choice"}
            for col_info in column_infos:
                col_name = col_info.name
                if col_name in user_configs:
                    continue
                current_spec = generator_specs.get(col_name)
                if current_spec is None:
                    continue
                if current_spec.generator_name not in _fallback_generators:
                    continue
                # For "choice" with non-empty choices, reconcile against the
                # column's CHECK IN (...) enum when one exists: the database
                # constraint is the hard truth and must win over name-rule
                # guesses (e.g., EXACT_MATCH_RULES maps ``gender`` to
                # ['male', 'female', 'other'] but CHECK says IN ('M', 'F')).
                # Without this, zero-config fill crashes on IntegrityError.
                if current_spec.generator_name == "choice" and current_spec.params.get("choices"):
                    enum_choices = self._check_enum_choices(col_info.name, check_constraints)
                    if enum_choices is not None:
                        generator_specs[col_name] = GeneratorSpec(
                            generator_name="choice",
                            params={"choices": enum_choices},
                            null_ratio=current_spec.null_ratio,
                        )
                    continue
                enhanced = self._schema_fallback.fallback_for_column(col_info, check_constraints, unique_list)
                if enhanced is not None:
                    generator_specs[col_name] = enhanced
        generator_specs = self._unique_adjuster.adjust(
            generator_specs, unique_columns, count, column_infos, check_constraints
        )
        generator_specs = self._relation.resolve_foreign_keys(
            table_name,
            generator_specs,
            unique_columns=unique_columns,
        )
        # Composite FK resolution: override single-column FK upgrades with
        # composite FK parent table columns. For columns that are part of both
        # a single-column FK and a composite FK (e.g., shipments.origin_wh_id
        # has FK to warehouses(id) AND composite FK to routes(origin_wh_id)),
        # the composite FK's parent table is the stricter constraint and must
        # be used as the sampling source. Also clears derive_from in
        # user_configs for composite FK columns (LLM may have set derive_from
        # that overrides the FK spec in the DAG builder).
        generator_specs = self._relation.resolve_composite_fks(
            table_name,
            generator_specs,
            user_configs=user_configs,
        )
        generator_specs = self._fill_composite_pk_integer_columns(column_infos, generator_specs)
        return generator_specs, user_configs, unique_columns, composite_unique

    @staticmethod
    def _check_enum_choices(col_name: str, check_constraints: list[Any]) -> list[Any] | None:
        """Return the literal choices of a single-column CHECK IN (...) enum, or None.

        Only deterministic single-column enums are resolved; cross-column or
        unparseable CHECKs stay in the AI/manual domain and return None.
        """
        for chk in check_constraints:
            parsed = CheckConstraintParser.parse(col_name, chk.expression)
            if parsed is not None and parsed.kind == "choice" and parsed.choices:
                return list(parsed.choices)
        return None

    @staticmethod
    def _fill_composite_pk_integer_columns(
        column_infos: list[Any],
        generator_specs: dict[str, Any],
    ) -> dict[str, Any]:
        """Give composite-PK INTEGER columns an integer generator instead of "skip".

        SQLite auto-generates a rowid only for a *single-column* ``INTEGER
        PRIMARY KEY``. An INTEGER column inside a composite PK (e.g., ``seq``
        in ``PRIMARY KEY (shipment_id, seq)``) has NO implicit default, so the
        mapper's L1b implicit-INTEGER-PK skip yields a NULL insert and crashes
        on NOT NULL. FK columns are untouched — they were already upgraded to
        ``foreign_key`` specs by ``resolve_foreign_keys``. Composite-PK
        uniqueness across the remaining columns is enforced by DataStream via
        ``composite_unique_constraints``.
        """
        pk_cols = [c for c in column_infos if c.is_primary_key]
        if len(pk_cols) <= 1:
            return generator_specs
        for col in pk_cols:
            if col.is_autoincrement:
                continue
            spec = generator_specs.get(col.name)
            if spec is None or spec.generator_name != "skip":
                continue
            if "INT" not in (col.type or "").upper():
                continue
            generator_specs[col.name] = GeneratorSpec(
                generator_name="integer",
                params={"min_value": 1, "max_value": 999999},
            )
        return generator_specs

    def _declare_zero_config_check_boundary(
        self,
        table_name: str,
        check_constraints: list[Any],
    ) -> None:
        """Emit an honest capability-boundary notice for zero-config generation.

        Zero-config mode maps columns purely by type and does NOT guarantee
        CHECK-constraint compliance. When the table has at least one single-column
        CHECK that the deterministic parser CAN resolve (i.e. a column whose value
        domain the CHECK actually constrains), warn the user and point them to the
        layered workflow: AI analysis (``ai-analyze``) or hand-written YAML for
        business-compliant data.

        Only columns with a resolvable CHECK are listed; cross-column / OR /
        column-reference CHECKs are intentionally left to the AI/manual domain and
        are not enumerated here. Message language follows ``self._locale``.
        """
        from sqlseed.core.check_parser import CheckConstraintParser

        expressions = [ck.expression for ck in check_constraints]
        constrained_columns = [
            col.name
            for col in self._schema.get_column_info(table_name)
            if CheckConstraintParser.parse_all(col.name, expressions) is not None
        ]
        if not constrained_columns:
            return
        zh = self._locale.lower().replace("-", "_").startswith("zh")
        cols = ", ".join(constrained_columns)
        if zh:
            msg = (
                f"表 '{table_name}' 的零配置模式仅按列类型生成数据，"
                f"不保证满足 CHECK 约束（涉及列: {cols}）。"
                f"若需业务合规数据，请改用 AI 分析（ai-analyze）或手写 YAML 配置。"
            )
        else:
            msg = (
                f"Zero-config mode for table '{table_name}' generates data by column type "
                f"only and does NOT guarantee CHECK-constraint compliance (columns: {cols}). "
                f"For business-compliant data, use AI analysis (ai-analyze) or a hand-written YAML config."
            )
        logger.warning(msg)

    def _build_stream(
        self,
        generator_specs: dict[str, Any],
        user_configs: dict[str, Any],
        unique_columns: set[str],
        transform: str | None,
        seed: int | None,
        table_name: str | None = None,
        composite_unique: list[list[str]] | None = None,
    ) -> DataStream:
        dag = ColumnDAG()
        col_configs_list = list(user_configs.values()) if user_configs else None
        # Fetch column_infos (when table_name is known) so the DAG can propagate
        # NOT NULL semantics onto each ColumnNode — the stream uses this to
        # suppress null_ratio-driven NULLs for NOT NULL columns.
        column_infos = None
        if table_name is not None:
            column_infos = self._schema.get_column_info(table_name)
        dag_nodes = dag.build(
            generator_specs,
            col_configs_list,
            unique_columns=unique_columns,
            column_infos=column_infos,
        )

        expr_engine = ExpressionEngine(db_adapter=self._db)
        constraint_solver = ConstraintSolver()

        transform_fn = None
        if transform:
            transform_fn = load_transform(transform)

        provider = self._registry.get(self._provider_name)

        # Extract cross-column comparison CHECK constraints so the DataStream
        # can enforce them at row-generation time (retry when violated).
        # Supports ``col1 != col2``, ``col1 > col2``, ``col1 < col2``,
        # ``col1 >= col2``, ``col1 <= col2``.
        # Without this, independently-sampled columns (e.g., start_time and
        # end_time with LIKE constraints that block derive_from) can violate
        # ordering CHECKs, causing batch-level IntegrityError.
        inequality_constraints: list[tuple[str, str, str]] = []
        if table_name is not None:
            try:
                check_constraints = self._db.get_check_constraints(table_name)
                for ck in check_constraints:
                    expr_ck = ck.expression.strip()
                    # Match ``col1 (op) col2`` for cross-column comparisons
                    m_ck = re.match(r"^(\w+)\s*(!=|>=|<=|>|<)\s*(\w+)\s*$", expr_ck, re.IGNORECASE)
                    if not m_ck:
                        # ``col1 IS NULL OR col1 OP col2`` — nullable ordered
                        # comparison, very common in real schemas (shipped_date,
                        # return_date, discharge_date, to_date, ...). NULL passes
                        # the CHECK; non-NULL values must satisfy the comparison.
                        # DataStream skips the check when either side is NULL,
                        # which matches this semantics exactly.
                        m_ck = re.match(
                            r"^(\w+)\s+IS\s+NULL\s+OR\s+\1\s*(!=|>=|<=|>|<)\s*(\w+)\s*$",
                            expr_ck,
                            re.IGNORECASE,
                        )
                    if m_ck:
                        col1_ck, op_ck, col2_ck = m_ck.group(1), m_ck.group(2), m_ck.group(3)
                        inequality_constraints.append((col1_ck, col2_ck, op_ck))
            except Exception:
                # Non-critical: if CHECK constraint extraction fails, proceed
                # without inequality enforcement (INSERT-time error will surface).
                pass

        return DataStream(
            dag_nodes=dag_nodes,
            provider=provider,
            expr_engine=expr_engine,
            constraint_solver=constraint_solver,
            transform_fn=transform_fn,
            seed=seed,
            composite_unique_constraints=composite_unique,
            inequality_constraints=inequality_constraints,
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
    ) -> tuple[dict[str, Any], dict[str, Any], set[str], list[list[str]]]:
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
            A 4-tuple (generator_specs, user_configs, unique_columns, composite_unique).
        """
        t_resolve = time.monotonic()
        if enrich and clear_before:
            specs, user_configs, unique_columns, composite_unique = self._resolve_specs(
                table_name, count, columns, column_configs, enrich
            )
            self._db.clear_table(table_name)
        else:
            if clear_before:
                self._db.clear_table(table_name)
            specs, user_configs, unique_columns, composite_unique = self._resolve_specs(
                table_name, count, columns, column_configs, enrich
            )
        logger.debug("resolve_specs", table_name=table_name, elapsed=f"{time.monotonic() - t_resolve:.3f}s")
        builtin_count = sum(
            1
            for s in specs.values()
            if s.generator_name not in {"string", "skip", "autoincrement", "__enrich__", "__derive__"}
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
        return specs, user_configs, unique_columns, composite_unique

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
