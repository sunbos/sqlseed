"""AutoHealOrchestrator — top-level entry point for `ai-analyze --auto-heal`.

Spec reference: Section 2.1 (write phase), Section 5 (wiring), Section 13.

Pipeline:
  1. SchemaSnapshot (Defense 8 — record schema_hash at startup).
  2. SubgraphSplitter (Defenses 2 + 6 — Tarjan SCC + megacluster breaking).
  3. For each subgraph: Layer 2 (validate) → Layer 3 (repair) → Layer 4 (heal).
  4. BrokenEdgeAligner post-repairs broken FK edges.
  5. Defense 8 optimistic lock: re-check schema_hash at write time.
  6. Emit YAML string.

Adversarial fixes vs. plan:
  - ``snapshot.foreign_keys`` does not exist; iterate
    ``snapshot.tables[t].foreign_keys`` and use ``fk["ref_table"]`` as target.
  - ``snapshot.get_columns(table_name)`` does not exist; use
    ``snapshot.tables[table_name].columns`` (list[str]) and
    ``column_types`` dict.
  - ``validator.validate(sg_config)`` is insufficient; real FastValidator
    requires a ``snapshot`` argument and returns ``ValidationResult`` (not a
    list). Duck-type: if the return value has a ``violations`` attribute,
    use it; otherwise treat the return value as a list of violations.
"""

from __future__ import annotations

import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import yaml
from sqlseed_ai._generator_names import (
    CANONICAL_NUMERIC_GENERATORS,
    DATE_GENERATORS,
    RELATION_GENERATORS,
    generator_name,
    needs_typed_source,
)
from sqlseed_ai.auto_heal import _check_inference, _cross_column_checks
from sqlseed_ai.auto_heal.time_budget import TimeBudgetController
from sqlseed_ai.healer.post_repair import BrokenEdgeAligner
from sqlseed_ai.healer.subgraph import SubgraphSplitter
from sqlseed_ai.repair.strategies import _is_phone_like
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

from sqlseed._utils.logger import get_logger
from sqlseed.config.models import GeneratorConfig
from sqlseed.core.mapper import ColumnMapper
from sqlseed.database._protocol import ColumnInfo
from sqlseed.generators._dispatch import GeneratorDispatchMixin

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed_ai.validator.schema_snapshot import TableMeta

logger = get_logger(__name__)


# Valid generator names accepted by the orchestrator's safety net. Includes:
# - All 36 generators in ``GeneratorDispatchMixin.GENERATOR_MAP`` (the
#   dispatch table that raises ``UnknownGeneratorError`` for unregistered
#   names at fill time).
# - Special generators handled by the orchestrator (not in GENERATOR_MAP):
#   ``autoincrement`` (PK autoincrement), ``foreign_key`` and
#   ``foreign_key_or_integer`` (FK columns), ``skip`` (ColumnMapper sentinel
#   for autoincrement PKs), ``__enrich__`` (enrichment marker).
# Used by Step 5.5 to detect LLM-hallucinated generator names (e.g.,
# ``sequence`` instead of ``template``/``autoincrement``) that would
# otherwise leak to the YAML and abort the entire fill.
_VALID_GENERATORS: frozenset[str] = frozenset(GeneratorDispatchMixin.GENERATOR_MAP.keys()) | frozenset(
    {"autoincrement", "foreign_key", "foreign_key_or_integer", "skip", "__enrich__"}
)


@lru_cache(maxsize=1)
def _get_column_mapper() -> ColumnMapper:
    """Return a shared ColumnMapper instance (cached).

    ColumnMapper is stateless after __init__ (custom rules are registered
    at startup), so a single shared instance is safe for concurrent reads.
    ``lru_cache(maxsize=1)`` avoids re-creating the mapper (and re-compiling
    29 regex patterns) on every column lookup.
    """
    return ColumnMapper()


def _infer_locale(snapshot: SchemaSnapshot) -> str:
    """Infer the best locale from schema CHECK constraints.

    Scans all phone-like columns for ``LENGTH(col) = N`` CHECK constraints.
    ``LENGTH = 11`` uniquely identifies Chinese mobile numbers (e.g.,
    ``13800138000``), so ``zh_CN`` is returned to make Faker's ``phone``
    generator produce 11-digit Chinese mobiles. Without this inference,
    the default ``en_US`` locale produces NANP-format phones (``+1 NPA-NXX-XXXX``,
    16 chars) that violate the ``CHECK LENGTH = 11`` constraint at fill time.

    For databases without phone LENGTH constraints, ``en_US`` is returned
    as the safe default.
    """
    _phone_length_re = re.compile(r"LENGTH\s*\(\s*(\w+)\s*\)\s*=\s*(\d+)")
    for table_meta in snapshot.tables.values():
        for constraint in table_meta.constraints:
            if constraint.get("type") != "check":
                continue
            expr = constraint.get("expression", "")
            if not isinstance(expr, str):
                continue
            if match := _phone_length_re.search(expr):
                col_name = match.group(1)
                length = int(match.group(2))
                if _is_phone_like(col_name) and length == 11:
                    return "zh_CN"
    return "en_US"


def _debug(msg: str) -> None:
    """Print a progress message to stderr for user-visible debugging.

    Used by ``ai-analyze`` to show what the auto-heal pipeline is doing in
    real time (snapshot, subgraph splitting, per-table validate/repair/heal,
    LLM calls, degraded columns). Output goes to stderr so it does not
    pollute the YAML written to stdout.
    """
    print(msg, file=sys.stderr, flush=True)


_CURRENCY_NAME_KEYWORDS = (
    "amount",
    "price",
    "fee",
    "cost",
    "balance",
    "total",
    "adjustment",
    "subtotal",
    "discount",
    "shipping",
    "tax",
    "salary",
    "payment",
)


class AutoHealOrchestrator:
    """Top-level orchestrator for the contract-driven self-healing pipeline."""

    def __init__(
        self,
        *,
        db_path: str | None = None,
        url: str | None = None,
        heal_orchestrator: Any,  # HealOrchestrator
        validator: Any,  # FastValidator
        total_budget_seconds: float = 300.0,
        max_scc_size: int = 3,
        max_retries: int = 3,
        verbose: bool = False,
    ) -> None:
        self._db_path = db_path
        self._url = url
        self._heal_orchestrator = heal_orchestrator
        self._validator = validator
        self._total_budget = total_budget_seconds
        self._max_scc_size = max_scc_size
        self._max_retries = max_retries
        self._verbose = verbose

    def run(
        self,
        *,
        broken_edges_inject: list[tuple[str, str]] | None = None,
        initial_config: dict[str, Any] | None = None,
        tables: list[str] | None = None,
        include_dependencies: bool = True,
        max_depth: int = 5,
    ) -> str:
        """Execute the full pipeline and return the final YAML config string."""
        snapshot, original_hash = self._capture_run_snapshot()
        initial_config, initial_tables, subgraphs, broken_edges = self._prepare_run_scope(
            snapshot, initial_config, tables, include_dependencies, max_depth, broken_edges_inject
        )
        # Time budget
        budget = TimeBudgetController(
            total_seconds=self._total_budget,
            table_count=len(snapshot.tables),
        )

        config = self._build_run_root_config(snapshot, initial_config)
        input_violations: set[tuple[str, str]] = set()
        self._process_run_subgraphs(
            _RunPhaseContext(config, snapshot, original_hash, budget, subgraphs, initial_tables, input_violations)
        )
        config = self._align_run_broken_edges(config, broken_edges)
        self._verify_run_schema_hash(original_hash)
        preserved_columns = self._capture_preserved_input_columns(config, initial_tables, input_violations)
        self._normalize_generated_columns(config, snapshot)

        self._restrict_conditional_range_sources(config, snapshot)

        self._stabilize_real_arithmetic_sources(config, snapshot)

        self._cap_derived_range_sources(config)

        self._apply_complex_check_null_fallbacks(config, snapshot)

        self._apply_status_null_conditions(config, snapshot)

        self._enforce_notnull_checks(config, snapshot)

        self._restore_input_columns_and_clean_output(config, preserved_columns)
        from sqlseed_ai.healer.candidate_validation import validate_candidate

        validate_candidate(config, snapshot)
        if self._verbose:
            table_count = len(config.get("tables", []))
            _debug(f"[ai-analyze] Step 6: emitting YAML ({table_count} tables) ...")
        yaml_str: str = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
        return yaml_str

    def _normalize_generated_columns(self, config: dict[str, Any], snapshot: SchemaSnapshot) -> None:

        # Step 5.5: Final param normalization + missing-generator repair.
        # This is a safety net: even if the validator didn't report a
        # violation for an invalid param (e.g., ``unique: true`` on an
        # ``integer`` generator), we strip it here to prevent runtime errors
        # during fill (e.g., ``MimesisProvider._gen_integer() got an
        # unexpected keyword argument 'unique'``).
        #
        # Additionally, the LLM sometimes returns ``generator: null`` for
        # columns (especially when it "simplifies" the config). This causes
        # fill failures because the core mapper treats null generator as
        # "skip". We repair missing generators by inferring from the params
        # (e.g., ``min_length`` → ``string``) or falling back to the
        # type-based placeholder.
        from sqlseed_ai.repair.strategies import _strip_invalid_params

        for tcfg in config.get("tables", []):
            self._normalize_generated_table(tcfg, snapshot, config, _strip_invalid_params)

    def _restrict_conditional_range_sources(self, config: dict[str, Any], snapshot: SchemaSnapshot) -> None:

        # Pattern 27 source-column choices constraint: when a multi-clause
        # CHECK like ``status = 'active' AND col >= 0 OR status = 'completed'
        # AND col >= 100 OR status = 'dropped' AND col < 100`` exists, the
        # source column (status) can ONLY take values mentioned in the clauses
        # ('active', 'completed', 'dropped'). Any other value (e.g.,
        # 'refunded') causes the CHECK to fail because no clause matches.
        # This safety net scans for Pattern 27 constraints and constrains the
        # source column's choice generator to only include allowed values.
        for tcfg in config.get("tables", []):
            self._restrict_table_conditional_sources(tcfg, snapshot)

    def _stabilize_real_arithmetic_sources(self, config: dict[str, Any], snapshot: SchemaSnapshot) -> None:

        # REAL precision safety net: PostgreSQL REAL (32-bit float) columns
        # with arithmetic equality CHECK constraints (e.g.,
        # ``delta = version_from * version_to``) fail when source columns
        # use float generators with fractional precision. Python computes
        # expressions in 64-bit float, but PostgreSQL stores and validates
        # CHECK constraints in 32-bit REAL — the arithmetic results diverge
        # due to rounding (e.g., 0.1 + 0.2 != 0.3 in 32-bit float). Using
        # integer source values (which are exactly representable in 32-bit
        # float when < 2^24 = 16777216) ensures the equality CHECK holds
        # exactly.
        #
        # This safety net scans for REAL columns with derive_from +
        # arithmetic expressions and converts their source columns from
        # ``float`` (with precision) to ``integer``. The max_value is
        # capped at 4000 to ensure products stay within the 32-bit exact
        # range (4000 * 4000 = 16M < 2^24).
        #
        # Decision test: any PostgreSQL database with REAL columns
        # participating in arithmetic equality CHECKs benefits. SQLite
        # uses 64-bit float for all floating-point types, so this safety
        # net is a no-op there (no REAL columns).
        for tcfg in config.get("tables", []):
            self._stabilize_table_real_arithmetic(tcfg, snapshot)

    def _cap_derived_range_sources(self, config: dict[str, Any]) -> None:

        # Derive_from random_float range cap: when a column has
        # ``derive_from`` with an expression like
        # ``random_float(value, 100.0)`` and the source column's
        # ``max_value`` exceeds the literal upper bound (100.0), the
        # expression produces invalid values (min > max) when the source
        # value exceeds the literal. Cap the source column's ``max_value``
        # to the literal to ensure the expression is always valid.
        #
        # Example: ``calibration >= min_threshold AND calibration <= 100.0``
        # — the LLM sets ``calibration`` to
        # ``derive_from: min_threshold, expression: random_float(value, 100.0)``
        # but leaves ``min_threshold`` with ``max_value: 999999.0``. When
        # ``min_threshold > 100.0``, ``random_float(value, 100.0)`` fails.
        # Capping ``min_threshold``'s ``max_value`` to ``100.0`` fixes this.
        for tcfg in config.get("tables", []):
            columns_rc = tcfg.get("columns", [])
            col_map_rc: dict[str, dict[str, Any]] = {c.get("name", ""): c for c in columns_rc}
            for c_rc in columns_rc:
                expr_rc = str(c_rc.get("expression", ""))
                derive_from_rc = c_rc.get("derive_from", "")
                if not derive_from_rc or not expr_rc:
                    continue
                # Match ``random_float(value, LITERAL)`` where LITERAL is a number
                if (m_rc := re.search(r"random_float\(value,\s*([\d.]+)\)", expr_rc)) is None:
                    continue
                literal_max_rc = float(m_rc.group(1))
                if (src_col_rc := col_map_rc.get(derive_from_rc)) is None:
                    continue
                src_params_rc = src_col_rc.get("params") or {}
                src_max_rc = src_params_rc.get("max_value")
                if src_max_rc is not None and float(src_max_rc) > literal_max_rc:
                    src_params_rc["max_value"] = literal_max_rc
                    src_col_rc["params"] = src_params_rc

    def _apply_complex_check_null_fallbacks(self, config: dict[str, Any], snapshot: SchemaSnapshot) -> None:

        # Complex CHECK null_ratio safety net: for nullable columns with
        # cross-column CHECK constraints that no Pattern (1-41) matched,
        # set null_ratio=1.0. These are typically complex multi-clause
        # conditional CHECKs like:
        #   ``is_normal = 0 OR test_value IS NULL OR
        #      (test_value >= ref_low AND test_value <= ref_high AND ...)``
        # where the ``IS NULL`` branch is the only safe fallback. The
        # existing ``_infer_cross_column_config`` handles 41 patterns but
        # can't match every possible complex CHECK — this safety net
        # catches the remainder by forcing NULL (which always satisfies
        # the ``IS NULL`` branch).
        #
        # IMPORTANT: this safety net is skipped when ANY CHECK constraint
        # requires the column to be NOT NULL (e.g.,
        # ``status = 'completed' AND completed_at IS NOT NULL``). Setting
        # null_ratio=1.0 in that case would violate the NOT NULL branch.
        #
        # Also overrides incorrect derive_from expressions that can't
        # satisfy the complex CHECK (e.g., LLM-set derive_from with a
        # simple expression that doesn't handle all conditional branches).
        #
        # Decision test: any database with complex conditional CHECKs
        # that weren't matched by the pattern engine benefits.
        for tcfg in config.get("tables", []):
            self._apply_table_complex_check_nulls(tcfg, snapshot)

    def _apply_status_null_conditions(self, config: dict[str, Any], snapshot: SchemaSnapshot) -> None:

        # Multi-clause conditional CHECK status-NULL safety net: for columns
        # referenced in multi-clause OR CHECKs like:
        #   ``((status = 'scheduled') AND (started_at IS NULL) AND (completed_at IS NULL))
        #    OR ((status = 'in_progress') AND (started_at IS NOT NULL) AND (completed_at IS NULL))
        #    OR ((status = 'completed') AND (cost > 0) AND (labor_time IS NOT NULL))
        #    OR (status = 'cancelled')``
        # extract the ``cond_col = 'V' AND col IS NULL`` patterns and modify
        # ``col`` to return None when ``cond_col`` matches the NULL-triggering
        # values. This handles 4-way conditional CHECKs that no Pattern (1-41)
        # matched because Pattern 30 only handles single-clause
        # ``col1 != VALUE OR col IS NULL`` (not multi-clause OR).
        #
        # Two cases:
        # 1. ``col`` already has ``derive_from``: wrap the existing expression
        #    with ``None if row.get('cond_col') in (V1, V2, ...) else <orig>``
        # 2. ``col`` has no ``derive_from`` (independent generator): find an
        #    anchor datetime column (same table, non-NULL datetime type) and
        #    set ``derive_from: cond_col`` with expression
        #    ``None if value in (V1, ...) else row['anchor'] + timedelta(...)``
        #
        # Decision test: R8 maintenance_logs_check3 (4-way conditional CHECK
        # on status + started_at + completed_at).
        for tcfg_sn in config.get("tables", []):
            self._apply_table_status_nulls(tcfg_sn, snapshot)

    def _enforce_notnull_checks(self, config: dict[str, Any], snapshot: SchemaSnapshot) -> None:

        # Safety net 7: Clear ``null_ratio: 1.0`` on columns that:
        # (a) have ``IS NOT NULL`` in their CHECK constraints, OR
        # (b) have other columns deriving from them via ``derive_from`` that
        #     are expected to produce non-NULL values (no null_ratio on the
        #     dependent).
        #
        # This handles three cases:
        # - R7 claims.approved_amount: LLM set null_ratio=1.0, but CHECK
        #   requires non-NULL when status IN ('approved','settled') — case (a)
        # - R4 usage_records.quota_limit: complex CHECK safety net set
        #   null_ratio=1.0, but metric_value (NOT NULL) derives from it —
        #   case (b)
        # - R4 organizations.parent_id: Step 0 (self-ref FK) set
        #   null_ratio=1.0, but CHECK requires non-NULL when
        #   org_type != 'root' — special case (c)
        #
        # For self-ref FK columns (case c), we CANNOT simply clear null_ratio
        # because the FK has no target rows during initial bulk fill (the
        # parent table is the same table, which is being filled for the first
        # time, so the shared pool is empty). Instead, we keep null_ratio=1.0
        # and restrict the conditional column's choices to only the
        # NULL-allowing value (e.g., org_type='root'), so both the FK
        # constraint and the CHECK constraint are satisfied:
        # - ``org_type = 'root' OR parent_id IS NOT NULL`` → 'root'='root' is
        #   TRUE, so the CHECK passes regardless of parent_id
        # - ``org_type != 'root' OR parent_id IS NULL`` → 'root'!='root' is
        #   FALSE, so parent_id must be NULL (satisfied by null_ratio=1.0)
        for tcfg_sn7 in config.get("tables", []):
            self._enforce_table_notnull_checks(tcfg_sn7, snapshot)

    def _restore_input_columns_and_clean_output(
        self, config: dict[str, Any], preserved_columns: dict[tuple[str, str], dict[str, Any]]
    ) -> None:

        # Step 6: emit YAML
        # Clean up internal debug fields and redundant empty params before
        # output. ``_degraded``/``degrade_reason`` are heal-time diagnostics
        # that should not appear in the final user-facing YAML — they leak
        # internal LLM failure state and confuse users. Empty ``params: {}``
        # is redundant since Pydantic defaults handle missing params.
        for tcfg in config.get("tables", []):
            tcfg["columns"] = [
                preserved_columns.get((tcfg["name"], column["name"]), column) for column in tcfg.get("columns", [])
            ]
            for c in tcfg.get("columns", []):
                c.pop("_degraded", None)
                c.pop("degrade_reason", None)
                if c.get("params") == {}:
                    c.pop("params", None)

    def _capture_run_snapshot(self) -> tuple[SchemaSnapshot, str]:
        # Step 1: snapshot (Defense 8)
        if self._verbose:
            _debug("[ai-analyze] Step 1: capturing schema snapshot ...")
        snapshot = SchemaSnapshot(db_path=self._db_path, url=self._url)
        original_hash = snapshot.schema_hash
        if self._verbose:
            _debug(f"[ai-analyze]   schema_hash={original_hash[:12]}... tables={list(snapshot.tables.keys())}")
        return snapshot, original_hash

    def _prepare_run_scope(
        self,
        snapshot: SchemaSnapshot,
        initial_config: dict[str, Any] | None,
        tables: list[str] | None,
        include_dependencies: bool,
        max_depth: int,
        broken_edges_inject: list[tuple[str, str]] | None,
    ) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]] | None, list[list[str]], list[tuple[str, str]]]:
        # Step 2: subgraph splitting (Defenses 2 + 6)
        if self._verbose:
            _debug("[ai-analyze] Step 2: splitting FK graph into subgraphs ...")
        splitter = SubgraphSplitter(max_scc_size=self._max_scc_size)
        fk_graph = self._build_fk_graph(snapshot)
        initial_config, initial_tables, tables, include_dependencies = self._prepare_initial_run_config(
            initial_config, tables, include_dependencies
        )
        fk_graph = self._select_run_fk_graph(snapshot, fk_graph, tables, include_dependencies, max_depth)
        subgraphs, broken_edges = splitter.split(fk_graph)
        if broken_edges_inject:
            broken_edges.extend(broken_edges_inject)
        if self._verbose:
            _debug(f"[ai-analyze]   subgraphs={subgraphs} broken_edges={broken_edges if broken_edges else 'none'}")
        return initial_config, initial_tables, subgraphs, broken_edges

    def _prepare_initial_run_config(
        self, initial_config: dict[str, Any] | None, tables: list[str] | None, include_dependencies: bool
    ) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]] | None, list[str] | None, bool]:
        initial_tables: dict[str, dict[str, Any]] | None = None
        if initial_config is not None:
            initial_config = deepcopy(initial_config)
            if self._db_path or self._url:
                initial_config.pop("url" if self._db_path else "db_path", None)
                initial_config["db_path" if self._db_path else "url"] = self._db_path or self._url
            validated = GeneratorConfig.model_validate(initial_config)
            names = [table.name for table in validated.tables]
            if len(names) != len(set(names)):
                raise ValueError("Config contains duplicate table names")
            initial_tables = {table["name"]: deepcopy(table) for table in initial_config.get("tables", [])}
            tables = names
            include_dependencies = False
        return initial_config, initial_tables, tables, include_dependencies

    def _select_run_fk_graph(
        self,
        snapshot: SchemaSnapshot,
        fk_graph: dict[str, list[str]],
        tables: list[str] | None,
        include_dependencies: bool,
        max_depth: int,
    ) -> dict[str, list[str]]:
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        if tables is not None:
            selected = set(tables)
            if unknown := selected - snapshot.tables.keys():
                raise ValueError(f"Unknown tables: {', '.join(sorted(unknown))}")
            frontier = selected.copy()
            for _ in range(max_depth if include_dependencies else 0):
                frontier = {parent for table in frontier for parent in fk_graph[table]} - selected
                frontier.intersection_update(snapshot.tables)
                selected.update(frontier)
                if not frontier:
                    break
            fk_graph = {
                table: [parent for parent in parents if parent in selected]
                for table, parents in fk_graph.items()
                if table in selected
            }
        return fk_graph

    def _build_run_root_config(self, snapshot: SchemaSnapshot, initial_config: dict[str, Any] | None) -> dict[str, Any]:
        # Step 3: per-subgraph validate → repair → heal
        # Include connection target so the YAML is directly fillable by
        # ``sqlseed fill --config <yaml>`` without requiring --db on the
        # command line. Inserted before "tables" for readability.
        # Explicitly include ``provider`` and ``locale`` so users can see
        # and modify these settings in the generated YAML. Without these
        # fields, the YAML omits the data engine (faker/mimesis/base) and
        # locale (en_US/zh_CN) — users don't know which provider is active
        # or what locale is used.
        #
        # Locale is inferred from schema CHECK constraints: when a phone
        # column has ``LENGTH(phone) = 11``, the locale is set to ``zh_CN``
        # so Faker generates 11-digit Chinese mobile numbers. Otherwise,
        # ``en_US`` is the safe default.
        inferred_locale = _infer_locale(snapshot)
        config: dict[str, Any] = deepcopy(initial_config) if initial_config is not None else {}
        if self._url:
            config.pop("db_path", None)
            config["url"] = self._url
        elif self._db_path:
            config.pop("url", None)
            config["db_path"] = self._db_path
        config.setdefault("provider", "faker")
        config.setdefault("locale", inferred_locale)
        config["tables"] = []
        if self._verbose:
            _debug(f"[ai-analyze] locale inferred: {inferred_locale}")
        return config

    def _process_run_subgraphs(self, context: _RunPhaseContext) -> None:
        for sg_idx, sg_tables in enumerate(context.subgraphs, 1):
            self._process_run_subgraph(context, sg_idx, sg_tables)

    def _process_run_subgraph(self, context: _RunPhaseContext, sg_idx: int, sg_tables: list[str]) -> None:
        config = context.config
        snapshot = context.snapshot
        original_hash = context.original_hash
        budget = context.budget
        subgraphs = context.subgraphs
        initial_tables = context.initial_tables
        input_violations = context.input_violations
        if budget.is_expired():
            logger.warning(
                "Time budget expired, falling back to defaults",
                remaining_tables=sg_tables,
            )
            if self._verbose:
                _debug(f"[ai-analyze]   TIME BUDGET EXPIRED for {sg_tables} — using defaults")
            if initial_tables is not None:
                raise RuntimeError("Time budget expired before the input config could be repaired")
            self._append_default_columns(config, sg_tables, snapshot)
            return

        if self._verbose:
            _debug(f"[ai-analyze] Step 3[{sg_idx}/{len(subgraphs)}]: building config for {sg_tables} ...")
        sg_config = (
            {"tables": [deepcopy(initial_tables[name]) for name in sg_tables]}
            if initial_tables is not None
            else self._build_subgraph_config(sg_tables, snapshot)
        )
        sg_config["provider"] = config["provider"]
        sg_config["locale"] = config["locale"]
        violations = self._validate(sg_config, snapshot)
        if initial_tables is not None:
            for violation in violations:
                input_violations.update((violation.table, column) for column in violation.columns)
        self._report_initial_run_violations(violations, sg_tables)
        if not violations:
            config["tables"].extend(sg_config["tables"])
            if self._verbose:
                _debug("[ai-analyze]   no violations — accepted as-is")
            return
        # Layer 3 + Layer 4: repair + heal
        if self._verbose:
            _debug("[ai-analyze]   invoking Layer 3 (repair) + Layer 4 (LLM heal) ...")
        result = self._heal_subgraph(sg_config, sg_tables, violations, snapshot, original_hash, budget)
        config["tables"].extend(result.get("tables", []))
        self._report_run_degraded_columns(result)

    def _report_initial_run_violations(self, violations: list[Any], sg_tables: list[str]) -> None:
        if self._verbose:
            _debug(f"[ai-analyze]   initial violations={len(violations) if violations else 0} tables={sg_tables}")
            if violations:
                for v in violations[:5]:
                    _debug(
                        f"[ai-analyze]     - {getattr(v, 'table', '?')}.{getattr(v, 'column', '?')}: "
                        f"{getattr(v, 'message', str(v))}"
                    )

    def _report_run_degraded_columns(self, result: dict[str, Any]) -> None:
        if self._verbose:
            # Report degraded columns (LLM failures that fell back to Core mapper)
            degraded = []
            for tcfg in result.get("tables", []):
                for c in tcfg.get("columns", []):
                    if c.get("_degraded"):
                        degraded.append(f"{tcfg['name']}.{c['name']}({c.get('degrade_reason', '?')})")
            if degraded:
                _debug(f"[ai-analyze]   degraded columns: {degraded}")
            else:
                _debug("[ai-analyze]   no degraded columns")

    def _align_run_broken_edges(self, config: dict[str, Any], broken_edges: list[tuple[str, str]]) -> dict[str, Any]:
        # Step 4: post-repair broken edges (Section 14)
        if broken_edges:
            if self._verbose:
                _debug(f"[ai-analyze] Step 4: repairing {len(broken_edges)} broken FK edges ...")
            aligner = BrokenEdgeAligner()
            config = aligner.align(config, broken_edges)
        elif self._verbose:
            _debug("[ai-analyze] Step 4: no broken FK edges to repair")
        return config

    def _verify_run_schema_hash(self, original_hash: str) -> None:
        # Step 5: Defense 8 optimistic lock — verify schema unchanged
        if self._verbose:
            _debug("[ai-analyze] Step 5: verifying schema unchanged (optimistic lock) ...")
        new_snapshot = SchemaSnapshot(db_path=self._db_path, url=self._url)
        if new_snapshot.schema_hash != original_hash:
            logger.error(
                "Defense 8: schema drift detected, aborting YAML write",
                original=original_hash,
                current=new_snapshot.schema_hash,
            )
            raise RuntimeError(f"Schema changed during auto-heal: {original_hash} -> {new_snapshot.schema_hash}")

    def _capture_preserved_input_columns(
        self,
        config: dict[str, Any],
        initial_tables: dict[str, dict[str, Any]] | None,
        input_violations: set[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        # Explicit input rules which validation/repair/healing left untouched
        # belong to the caller. Preserve them across the inference safety net.
        preserved_columns: dict[tuple[str, str], dict[str, Any]] = {}
        if initial_tables is not None:
            for table in config["tables"]:
                originals = {column["name"]: column for column in initial_tables[table["name"]].get("columns", [])}
                for column in table.get("columns", []):
                    key = (table["name"], column["name"])
                    if key not in input_violations and column == originals.get(column["name"]):
                        preserved_columns[key] = deepcopy(column)
        return preserved_columns

    def _normalize_generated_table(
        self,
        tcfg: dict[str, Any],
        snapshot: SchemaSnapshot,
        config: dict[str, Any],
        _strip_invalid_params: Callable[[dict[str, Any], str], dict[str, Any]],
    ) -> None:
        table_name = tcfg.get("name", "")
        # Calculate required sequence digit width based on table row count.
        # Dynamic sizing avoids both under-padding (format breaks at 1000+
        # rows when ``:03d`` expands to 4 digits) and over-padding (5+
        # digits for a 100-row table looks odd). Minimum 4 digits covers
        # the common 1000-row default; larger tables auto-expand.
        table_count = tcfg.get("count") or 1000
        req_digits = max(4, len(str(int(table_count))))
        meta = snapshot.tables.get(table_name)
        # Pre-scan: detect source columns of derive_from+timedelta
        # expressions. When a column derives from another column using
        # ``timedelta(...)`` arithmetic (e.g.,
        # ``value - timedelta(days=random_int(1, 365))``), the source
        # column MUST be a date/datetime generator. If the LLM set it
        # to ``string`` (common for SQLite DATE columns stored as TEXT),
        # the fill crashes with
        # ``TypeError: unsupported operand type(s) for -: 'str' and
        # 'datetime.timedelta'``. Collect these source columns here so
        # the main loop can upgrade them from ``string`` to
        # ``datetime``/``date`` before the derive_from expression is
        # evaluated at fill time.
        timedelta_sources = self._collect_timedelta_sources(tcfg, meta)
        # State machine pre-pass: detect conditional NULL date patterns.
        # Pattern: ``col1 != 'VALUE' OR date_col IS NOT NULL`` means
        # date_col must be non-NULL when col1 == VALUE. Combined with
        # date ordering constraints (``date_col2 IS NULL OR date_col2 >=
        # date_col1``), this forms a state machine where later dates
        # depend on earlier dates being non-NULL.
        #
        # Example (orders table):
        #   status != 'paid' OR paid_at IS NOT NULL
        #   status != 'shipped' OR shipped_at IS NOT NULL
        #   shipped_at IS NULL OR shipped_at >= paid_at
        #
        # Transitive closure: paid_at must be non-NULL for statuses
        # {'paid', 'shipped', 'delivered'} (because shipped_at requires
        # paid_at, and delivered_at requires shipped_at).
        #
        # Result: ``state_machine_dates[date_col] = (status_col, required_statuses)``
        # Used in the per-column loop to set conditional derive_from.
        state_machine_dates = self._collect_state_machine_dates(meta)
        # Phone LENGTH pre-pass: detect LENGTH(phone) = N or
        # LENGTH(phone) >= N CHECK constraints (may have a
        # ``col IS NULL OR`` prefix). When locale is zh_CN and N=11,
        # the faker phone_number() generator may produce numbers with
        # dashes/spaces that don't satisfy LENGTH=11 (e.g.,
        # "138-1234-5678" has LENGTH=13). Switch to pattern generator
        # with Chinese mobile number regex to guarantee compliance.
        phone_length_constraints = self._collect_phone_length_constraints(meta)
        context = _ColumnRuleContext(
            config,
            snapshot,
            tcfg,
            table_name,
            req_digits,
            meta,
            timedelta_sources,
            state_machine_dates,
            phone_length_constraints,
            _strip_invalid_params,
        )
        for c in tcfg.get("columns", []):
            self._normalize_generated_column(context, c)

        self._upgrade_restored_timedelta_sources(tcfg, meta)

    def _restrict_table_conditional_sources(self, tcfg: dict[str, Any], snapshot: SchemaSnapshot) -> None:
        table_name = tcfg.get("name", "")
        if (meta := snapshot.tables.get(table_name)) is None:
            return
        for c_p27_src in meta.constraints:
            if c_p27_src.get("type") != "check":
                continue
            expr_p27_src = c_p27_src.get("expression", "")
            if " OR " not in expr_p27_src or " AND " not in expr_p27_src:
                continue
            # Find all clauses: other_col = 'Vi' AND target_col OP Xi
            clause_re_src = (
                r"(\w+)\s*=\s*'([^']+)'\s+AND\s+(\w+)\s*"
                r"(>=|<=|>|<)\s*(-?[0-9]+(?:\.[0-9]+)?)"
            )
            clauses_src = re.findall(clause_re_src, expr_p27_src)
            if len(clauses_src) < 2:
                continue
            src_col_p27 = clauses_src[0][0]
            # All clauses must reference the same source column
            if not all(cl[0] == src_col_p27 for cl in clauses_src):
                continue
            allowed_values = [cl[1] for cl in clauses_src]
            # Find the source column in the config and constrain its choices
            for col_cfg in tcfg.get("columns", []):
                if col_cfg.get("name") == src_col_p27 and col_cfg.get("generator") == "choice":
                    old_choices = col_cfg.get("params", {}).get("choices", [])
                    # Only keep choices that are in the allowed values
                    new_choices = [v for v in old_choices if v in allowed_values]
                    if new_choices and len(new_choices) < len(old_choices):
                        col_cfg["params"]["choices"] = new_choices

    def _stabilize_table_real_arithmetic(self, tcfg: dict[str, Any], snapshot: SchemaSnapshot) -> None:
        table_name_r = tcfg.get("name", "")
        if (meta_r := snapshot.tables.get(table_name_r)) is None:
            return
        columns_r = tcfg.get("columns", [])
        col_map_r: dict[str, dict[str, Any]] = {c.get("name", ""): c for c in columns_r}
        # Collect REAL columns with arithmetic derive_from expressions
        real_derived_cols_r = self._collect_real_arithmetic_columns(columns_r, meta_r)
        # Convert source columns from float to integer
        for derived_col_r in real_derived_cols_r:
            source_cols_r: list[str] = []
            if derive_from_r := derived_col_r.get("derive_from", ""):
                source_cols_r.append(derive_from_r)
            expr_r = derived_col_r.get("expression", "")
            for m_r in re.finditer(r"row\['([^']+)'\]", expr_r):
                source_cols_r.append(m_r.group(1))
            # Dedupe preserving order
            source_cols_r = list(dict.fromkeys(source_cols_r))
            for src_name_r in source_cols_r:
                self._stabilize_real_source_column(col_map_r, src_name_r)

    def _apply_table_complex_check_nulls(self, tcfg: dict[str, Any], snapshot: SchemaSnapshot) -> None:
        table_name_c = tcfg.get("name", "")
        if (meta_c := snapshot.tables.get(table_name_c)) is None:
            return
        for c_c in tcfg.get("columns", []):
            self._apply_column_complex_check_null(tcfg, meta_c, c_c)

    def _apply_table_status_nulls(self, tcfg_sn: dict[str, Any], snapshot: SchemaSnapshot) -> None:
        table_name_sn = tcfg_sn.get("name", "")
        if (meta_sn := snapshot.tables.get(table_name_sn)) is None:
            return
        columns_sn = tcfg_sn.get("columns", [])
        col_map_sn: dict[str, dict[str, Any]] = {c.get("name", ""): c for c in columns_sn}
        # Collect NULL-triggering values per (col, cond_col)
        # null_triggers[col][cond_col] = set of values that require col IS NULL
        null_triggers = self._collect_status_null_triggers(meta_sn)
        # Apply null_triggers to each affected column
        for col_sn, triggers_sn in null_triggers.items():
            self._apply_column_status_null(meta_sn, col_map_sn, columns_sn, col_sn, triggers_sn)

    def _enforce_table_notnull_checks(self, tcfg_sn7: dict[str, Any], snapshot: SchemaSnapshot) -> None:
        table_name_sn7 = tcfg_sn7.get("name", "")
        if (meta_sn7 := snapshot.tables.get(table_name_sn7)) is None:
            return
        # Compute self-ref FK columns for this table (Step 0 logic mirror)
        self_ref_fk_cols_sn7: set[str] = set()
        for fk_sn7 in meta_sn7.foreign_keys:
            if fk_sn7.get("ref_table") == table_name_sn7:
                for fc_sn7 in fk_sn7.get("columns", []):
                    self_ref_fk_cols_sn7.add(fc_sn7)
        fk_cols_set_sn7: set[str] = set()
        for fk_sn7 in meta_sn7.foreign_keys:
            for fc_sn7 in fk_sn7.get("columns", []):
                fk_cols_set_sn7.add(fc_sn7)
        # Build derive_from dependency map: source_col -> [dependent_cols]
        derive_dependents_sn7: dict[str, list[str]] = {}
        for c_dep in tcfg_sn7.get("columns", []):
            dep_name = c_dep.get("derive_from")
            if isinstance(dep_name, str):
                derive_dependents_sn7.setdefault(dep_name, []).append(c_dep.get("name", ""))
        context = _NotNullRuleContext(tcfg_sn7, meta_sn7, self_ref_fk_cols_sn7, fk_cols_set_sn7, derive_dependents_sn7)
        for c_sn7 in tcfg_sn7.get("columns", []):
            self._enforce_column_notnull_check(context, c_sn7)

    def _collect_timedelta_sources(self, tcfg: dict[str, Any], meta: TableMeta | None) -> dict[str, str]:
        timedelta_sources: dict[str, str] = {}  # col_name -> "date"|"datetime"
        for _c in tcfg.get("columns", []):
            if _c.get("derive_from") and "timedelta" in str(_c.get("expression", "")):
                src = _c["derive_from"]
                if isinstance(src, str) and src not in timedelta_sources:
                    src_type = (meta.column_types.get(src, "") if meta else "") or ""
                    if _is_date_only_type(src_type):
                        timedelta_sources[src] = "date"
                    else:
                        timedelta_sources[src] = "datetime"
        return timedelta_sources

    def _collect_state_machine_dates(self, meta: TableMeta | None) -> dict[str, tuple[str, set[str]]]:
        state_machine_dates: dict[str, tuple[str, set[str]]] = {}
        if meta is None:
            return state_machine_dates
        # Step 1: find direct status requirements for each date col.
        # Maps date_col -> (status_col, set of VALUEs requiring non-NULL)
        _direct_reqs = self._collect_direct_date_requirements(meta)
        # Step 2: build date dependency graph from ordering constraints.
        # ``date_col2 IS NULL OR date_col2 >= date_col1`` means
        # date_col2 depends on date_col1 (date_col1 must be non-NULL
        # when date_col2 is non-NULL).
        _date_deps = self._collect_date_dependency_graph(meta)
        # Step 3: compute transitive closure of required statuses.
        # If date_col2 depends on date_col1 (date_col2 IS NULL OR
        # date_col2 >= date_col1), then date_col1 must also be
        # non-NULL for all statuses that require date_col2.
        # Use fixpoint iteration to handle multi-level chains:
        # paid_at → shipped_at → delivered_at means paid_at must
        # be non-NULL for {'paid', 'shipped', 'delivered'}.
        for date_col, (status_col, direct_vals) in _direct_reqs.items():
            state_machine_dates[date_col] = (status_col, set(direct_vals))
        _changed = True
        while _changed:
            _changed = False
            for date_col, (_sc, all_vals) in state_machine_dates.items():
                # set 是可变对象：用别名做 |= 原地合并即写回字典中的集合，
                # 避免直接改写 for 循环变量（PLW2901）。
                merged_vals = all_vals
                for dep_col, src_col in _date_deps.items():
                    if src_col == date_col and dep_col in state_machine_dates:
                        dep_vals = state_machine_dates[dep_col][1]
                        before = len(merged_vals)
                        merged_vals |= dep_vals
                        if len(merged_vals) > before:
                            _changed = True
        return state_machine_dates

    def _collect_phone_length_constraints(self, meta: TableMeta | None) -> dict[str, int]:
        phone_length_constraints: dict[str, int] = {}
        if meta is not None:
            for ctr in meta.constraints:
                if ctr.get("type") != "check":
                    continue
                expr_pl = ctr.get("expression", "")
                if not isinstance(expr_pl, str):
                    continue
                # Use search (not match) because the LENGTH constraint
                # may have a prefix like ``phone IS NULL OR``.
                m_pl = re.search(
                    r"LENGTH\s*\(\s*(\w+)\s*\)\s*=\s*(\d+)",
                    expr_pl,
                    re.IGNORECASE,
                )
                if m_pl:
                    phone_length_constraints[m_pl.group(1)] = int(m_pl.group(2))
                else:
                    m_pl_ge = re.search(
                        r"LENGTH\s*\(\s*(\w+)\s*\)\s*>=\s*(\d+)",
                        expr_pl,
                        re.IGNORECASE,
                    )
                    if m_pl_ge:
                        phone_length_constraints[m_pl_ge.group(1)] = int(m_pl_ge.group(2))
        return phone_length_constraints

    def _normalize_generated_column(self, context: _ColumnRuleContext, c: dict[str, Any]) -> None:
        _strip_invalid_params = context._strip_invalid_params
        # Treat ``?`` placeholder as missing generator. The LLM
        # sometimes emits ``generator: '?'`` when it cannot decide
        # (especially for nullable columns like ``closed_at``). The
        # ProgressiveDegrader also leaves ``?`` as a sentinel for
        # columns it gave up on. Without this normalization, the
        # ``?`` leaks to the YAML and causes
        # ``UnknownGeneratorError: Unknown generator '?'`` at fill
        # time, aborting the entire table. By clearing it here, the
        # downstream missing-generator repair path (line 256:
        # ``if not gen and not has_derive``) kicks in and delegates
        # to the Core ColumnMapper for semantic name matching.
        if (gen := generator_name(c.get("generator"))) in {None, "?", ""}:
            gen = None
            c.pop("generator", None)
        gen = self._repair_phone_length_generator(context, c, gen)
        gen = self._repair_timedelta_source_generator(context, c, gen)
        # Derived-mode columns (``derive_from`` + ``expression``) are
        # mutually exclusive with source-mode (``generator`` +
        # ``params``) per the ``ColumnConfig`` model validator.
        # Skip generator inference AND param stripping for derived
        # columns — otherwise we'd add a ``generator`` to a column
        # that already has ``derive_from`` and trigger a Pydantic
        # ValidationError when the YAML is loaded downstream.
        has_derive = bool(c.get("derive_from"))
        has_derive = self._remove_like_derived_rule(context, c, has_derive)

        # State machine date conditional NULL safety net:
        # When a date column has a CHECK constraint like
        # ``status != 'paid' OR paid_at IS NOT NULL``, it means the
        # date must be non-NULL only when status matches specific
        # values. Without this safety net, the date is generated
        # unconditionally (always non-NULL), which is business-
        # incorrect (e.g., pending orders shouldn't have paid_at).
        #
        # This net uses the transitive closure computed in the
        # pre-pass (``state_machine_dates``) to set a conditional
        # derive_from that generates NULL when the status doesn't
        # match, and a real date when it does.
        #
        # Two cases:
        #   (a) No existing derive_from → set derive_from to
        #       created_at (or another base date column) with
        #       conditional expression.
        #   (b) Existing derive_from (from Pattern 1, e.g.,
        #       shipped_at derives from paid_at) → wrap the
        #       expression with status condition + None-guard.
        col_name_sm = c.get("name", "")
        has_derive = self._apply_state_machine_generator(context, c, has_derive, col_name_sm)
        self._guard_state_machine_expression(context, c, has_derive, col_name_sm)

        # Mutual-exclusivity enforcement: the LLM occasionally emits
        # BOTH ``derive_from`` AND ``generator`` for the same column
        # (e.g., ``derive_from: dest_wh_id, expression: value - 1 if
        # value > 1 else value + 1, generator: integer``). The
        # ``ColumnConfig`` Pydantic model enforces mutual exclusivity
        # between source-mode (``generator`` + ``params``) and
        # derived-mode (``derive_from`` + ``expression``). Without
        # this cleanup, the YAML triggers ``ValidationError: cannot
        # use both 'generator' and 'derive_from'`` and the entire
        # fill aborts. When ``derive_from`` survived the LIKE safety
        # net above, strip any leftover ``generator``/``params`` to
        # enforce the contract. This is a generic LLM-output cleanup
        # — it benefits any database where the LLM emits both modes.
        if has_derive:
            c.pop("generator", None)
            c.pop("params", None)
            gen = None

        # Template-string-in-generator repair: the LLM occasionally
        # returns the template value directly in the ``generator``
        # field (e.g., ``generator: 'NAME-{sequence:04d}'``) instead
        # of the correct ``generator: template, params: {template:
        # 'NAME-{sequence:04d}'}``. Detect this by checking for
        # placeholder braces and rewrite to the proper form. Without
        # this, the dispatch layer raises ``UnknownGeneratorError``
        # and the entire fill aborts.
        if gen and isinstance(gen, str) and "{" in gen and "}" in gen and gen not in ("template",):
            c["generator"] = "template"
            c["params"] = {"template": gen}
            return
        gen = self._clear_unknown_generator(context, c, gen)
        gen = self._repair_uuid_generator(context, c, gen, has_derive)
        gen = self._repair_uuid_primary_generator(context, c, gen, has_derive)
        gen = self._repair_string_check_generator(context, c, gen, has_derive)
        gen = self._repair_fixed_length_semantic_generator(context, c, gen, has_derive)
        gen = self._repair_unique_template_generator(context, c, gen, has_derive)
        self._repair_phone_bounds(context, c, gen, has_derive)
        gen = self._repair_unconstrained_fk_fallback(context, c, gen, has_derive)
        gen = self._repair_pattern_length(context, c, gen, has_derive)

        # Currency precision rounding: ``derive_from`` expressions
        # with float arithmetic (e.g., ``value * random_float(0.5, 1.0)``)
        # produce IEEE 754 results with 15+ decimal places like
        # ``844.6484506188955``. Frontend forms send currency values
        # with at most 2 decimal places (``844.65``). This safety net
        # wraps the expression with ``round(result, 2)`` for columns
        # whose name matches currency-related keywords.
        # Decision test: any ``derive_from`` column with a currency-
        # related name benefits — without this, the database stores
        # ``844.6484506188955`` instead of ``844.65``, which no real
        # frontend would ever submit.
        _col_name_lower = c.get("name", "").lower()
        self._normalize_currency_precision(context, c, gen, has_derive, _col_name_lower)
        self._tighten_numeric_bounds(context, c, gen, has_derive, _col_name_lower)
        gen = self._limit_integer_scale(context, c, gen, has_derive, _col_name_lower)
        self._default_coupon_null_ratio(context, c, has_derive, _col_name_lower)
        has_derive = self._derive_variant_value(context, c, gen, has_derive, _col_name_lower)
        self._guard_inventory_movement_quantity(context, c, has_derive, _col_name_lower)
        gen = self._preserve_check_enum_generator(context, c, gen, has_derive)

        params: dict[str, Any] = c.get("params") or {}
        params = self._recover_missing_template_params(context, c, gen, params)
        self._resize_sequence_template(context, c, gen, params)
        self._repair_template_character_sets(context, c, gen, params)
        gen = self._infer_missing_column_generator(context, c, gen, has_derive, params)
        gen, params = self._reapply_single_column_checks(context, c, gen, has_derive, params)
        has_derive = self._restore_cross_column_derivation(context, c, has_derive)

        # Strip invalid params (only for source-mode columns)
        if isinstance(params, dict) and gen and not has_derive:
            c["params"] = _strip_invalid_params(params, gen)
        gen, params = self._preserve_unique_exact_length(context, c, gen, has_derive, params)

    def _upgrade_restored_timedelta_sources(self, tcfg: dict[str, Any], meta: TableMeta | None) -> None:
        # Second-pass timedelta source upgrade: the pre-scan at the
        # top of this table loop collects timedelta source columns
        # based on the config AS IT WAS when the pre-scan ran. However,
        # the cross-column derive_from restoration above may RE-ADD
        # ``derive_from`` + ``expression`` (with ``timedelta``) to
        # columns where the LLM had stripped it. These newly-restored
        # timedelta sources were NOT detected by the pre-scan, so their
        # source columns were not upgraded from ``string`` to
        # ``date``/``datetime``. This second pass catches any such
        # columns and upgrades their source columns now, preventing
        # ``TypeError: unsupported operand type(s) for -: 'str' and
        # 'datetime.timedelta'`` at fill time.
        for column in tcfg.get("columns", []):
            if not column.get("derive_from") or "timedelta" not in str(column.get("expression", "")):
                continue
            source_name = column["derive_from"]
            if isinstance(source_name, str):
                self._upgrade_restored_timedelta_source(tcfg, meta, source_name)

    def _repair_phone_length_generator(self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any) -> Any:
        config = context.config
        phone_length_constraints = context.phone_length_constraints
        # Phone LENGTH safety net: when a phone column has a
        # LENGTH=N CHECK constraint, switch from the faker phone
        # generator to a pattern generator that produces exactly N
        # digits. The faker zh_CN phone_number() often includes
        # dashes/spaces that violate LENGTH constraints (e.g.,
        # "138-1234-5678" has LENGTH=13, not 11). For zh_CN with
        # N=11, use the Chinese mobile number regex
        # (1[3-9]\d{9}) to produce realistic 11-digit numbers.
        col_name_pl = c.get("name", "")
        if gen == "phone" and col_name_pl in phone_length_constraints and not c.get("derive_from"):
            req_len_pl = phone_length_constraints[col_name_pl]
            locale_pl = config.get("locale", "en_US")
            if locale_pl == "zh_CN" and req_len_pl >= 10:
                # Chinese mobile numbers are always 11 digits
                # (1[3-9]\d{9}), which satisfies both = 11 and
                # >= 10 constraints.
                c.pop("generator", None)
                c.pop("params", None)
                c["generator"] = "pattern"
                c["params"] = {"regex": r"^1[3-9]\d{9}$"}
            elif req_len_pl > 0:
                c.pop("generator", None)
                c.pop("params", None)
                c["generator"] = "pattern"
                c["params"] = {"regex": rf"^\d{{{req_len_pl}}}$"}
            gen = c.get("generator")
        return gen

    def _repair_timedelta_source_generator(self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any) -> Any:
        timedelta_sources = context.timedelta_sources
        # Timedelta source upgrade: if this column is a source for a
        # derive_from+timedelta expression (detected in the pre-scan
        # above) and its generator is ``string`` or missing, upgrade
        # it to ``date``/``datetime``. Without this, the derive_from
        # expression (e.g., ``value - timedelta(days=...)``) crashes
        # at fill time with ``TypeError: unsupported operand type(s)
        # for -: 'str' and 'datetime.timedelta'`` because the string
        # generator produces ``str`` values, not date objects.
        col_name_55 = c.get("name", "")
        if col_name_55 in timedelta_sources and needs_typed_source(gen):
            target_gen = timedelta_sources[col_name_55]
            # Skip if this column already has derive_from.
            # Derived-mode columns don't need a generator — the
            # expression produces the correct type from the
            # source column (e.g., ``value + timedelta(...)``
            # where value is a date produces a date). Setting
            # generator here would create a Pydantic
            # ValidationError (both generator and derive_from).
            # This happens when a column is BOTH a source for
            # another column's derive_from AND itself derives
            # from yet another column (e.g., next_inspection
            # derives from purchase_date, and last_inspection
            # derives from next_inspection).
            if not c.get("derive_from"):
                gen = target_gen
                c["generator"] = target_gen
                c.pop("params", None)
                c["params"] = {}
        return gen

    def _remove_like_derived_rule(self, context: _ColumnRuleContext, c: dict[str, Any], has_derive: bool) -> bool:
        meta = context.meta

        # Arithmetic-on-string safety net: if the column (or its
        # source column) has a LIKE constraint, it stores formatted
        # strings (e.g., "HH:MM" time strings), NOT datetime objects
        # or numbers. ANY ``derive_from`` expression that does
        # arithmetic on ``value`` (``value + ...``, ``value - ...``,
        # ``value * ...``, ``timedelta(...)``) would fail at fill
        # time with ``TypeError: can only concatenate str (not X)
        # to str``. Strip the derive_from so the missing-generator
        # repair path picks a safe generator (e.g., ``pattern`` for
        # the LIKE format). This catches both LLM-generated and
        # stale deterministic-inference expressions.
        if has_derive and meta is not None:
            expr_str = str(c.get("expression", ""))
            # Detect arithmetic on ``value``: ``value +``, ``value -``,
            # ``value *``, or ``timedelta`` (which implies date math).
            has_arith = any(pat in expr_str for pat in ("value +", "value -", "value *", "value/", "timedelta"))
            if has_arith:
                col_name_55 = c.get("name", "")
                src_col_55 = c.get("derive_from", "")
                if _has_like_constraint(col_name_55, meta.constraints) or _has_like_constraint(
                    src_col_55, meta.constraints
                ):
                    c.pop("derive_from", None)
                    c.pop("expression", None)
                    has_derive = False
        return has_derive

    def _apply_state_machine_generator(
        self, context: _ColumnRuleContext, c: dict[str, Any], has_derive: bool, col_name_sm: str
    ) -> bool:
        meta = context.meta
        state_machine_dates = context.state_machine_dates
        if meta is not None and col_name_sm in state_machine_dates and not has_derive:
            status_col_sm, required_vals_sm = state_machine_dates[col_name_sm]
            col_type_sm = meta.column_types.get(col_name_sm, "")
            is_date_sm = _is_date_column(col_name_sm) or "DATE" in col_type_sm.upper() or "TIME" in col_type_sm.upper()
            if is_date_sm:
                # Find a base date column to derive from
                base_col_sm: str | None = None
                for bc in ("created_at", "updated_at", "opened_at", "added_at"):
                    if bc in meta.columns and bc != col_name_sm:
                        base_col_sm = bc
                        break
                if base_col_sm is None:
                    # Fall back to any other date column
                    for other_col in meta.columns:
                        if other_col != col_name_sm and _is_date_column(other_col):
                            base_col_sm = other_col
                            break
                if base_col_sm is not None:
                    vals_repr = ", ".join(f"'{v}'" for v in sorted(required_vals_sm))
                    c.pop("generator", None)
                    c.pop("params", None)
                    c.pop("null_ratio", None)
                    c["derive_from"] = base_col_sm
                    c["expression"] = (
                        f"None if row['{status_col_sm}'] not in ({vals_repr}) "
                        f"else value + timedelta(hours=random_int(1, 168))"
                    )
                    has_derive = True
        return has_derive

    def _guard_state_machine_expression(
        self, context: _ColumnRuleContext, c: dict[str, Any], has_derive: bool, col_name_sm: str
    ) -> None:
        meta = context.meta
        state_machine_dates = context.state_machine_dates
        # Case (b): existing derive_from — fix the status condition
        # using the transitive closure. The LLM often generates an
        # incomplete status set (e.g., ``paid_at`` only includes
        # 'paid', 'shipped' but misses 'delivered' which is required
        # by the transitive dependency chain delivered_at →
        # shipped_at → paid_at). This net replaces the status set
        # with the correct one from ``state_machine_dates``.
        if meta is not None and col_name_sm in state_machine_dates and has_derive and "derive_from" in c:
            status_col_sm2, required_vals_sm2 = state_machine_dates[col_name_sm]
            existing_expr = c.get("expression", "")
            src_col_sm = c.get("derive_from", "")
            vals_repr2 = ", ".join(f"'{v}'" for v in sorted(required_vals_sm2))
            if isinstance(existing_expr, str) and existing_expr:
                # Try to extract the inner expression (everything
                # after the status condition) and replace the
                # status set with the correct transitive closure.
                # Pattern: None if row['status'] not in (...) else INNER
                m_replace = re.match(
                    r"^None if row\['\w+'\] not in \([^)]*\) else (.+)$",
                    existing_expr,
                )
                if m_replace:
                    inner_expr = m_replace.group(1)
                    # If the source column is also in
                    # state_machine_dates (i.e., it might be NULL
                    # when its own status condition isn't met),
                    # ensure a None-guard exists.
                    if src_col_sm in state_machine_dates and "None if value is None" not in inner_expr:
                        inner_expr = f"(None if value is None else {inner_expr})"
                    c["expression"] = f"None if row['{status_col_sm2}'] not in ({vals_repr2}) else {inner_expr}"
                elif (
                    f"row['{status_col_sm2}']" not in existing_expr
                    and "None if value is None" not in existing_expr
                    and src_col_sm in state_machine_dates
                ):
                    # Fall back to wrapping for expressions without
                    # a status condition (avoid double-wrapping).
                    c["expression"] = (
                        f"None if row['{status_col_sm2}'] not in ({vals_repr2}) "
                        f"else (None if value is None else {existing_expr})"
                    )

    def _clear_unknown_generator(self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any) -> Any:

        # Invalid generator detection: the LLM may emit generator
        # names that don't exist in the dispatch table (e.g.,
        # ``sequence`` instead of ``template``/``autoincrement``,
        # ``increment`` instead of ``autoincrement``). The ``?``
        # normalization above only catches the explicit ``?``
        # sentinel and empty strings — other invalid names leak to
        # the YAML and cause ``UnknownGeneratorError`` at fill time,
        # aborting the entire table. Clearing the generator here
        # lets the downstream missing-generator repair path delegate
        # to the Core ColumnMapper for semantic name matching or
        # param-based inference. This is a generic LLM-output
        # cleanup that benefits any database where the LLM
        # hallucinates a non-existent generator name.
        if gen is not None and generator_name(gen) not in _VALID_GENERATORS:
            gen = None
            c.pop("generator", None)
        return gen

    def _repair_uuid_generator(self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool) -> Any:
        meta = context.meta

        # UUID column semantic upgrade: when the column name contains
        # ``uuid`` (e.g., ``tenant_uuid``, ``org_uuid``, ``api_key_uuid``)
        # and the LLM picked a non-UUID generator (e.g., ``pattern``
        # with ``[A-Za-z0-9]{36}`` or ``string``), upgrade to the
        # ``uuid`` generator. The ``pattern`` generator with a 36-char
        # regex satisfies ``CHECK (LENGTH(col) = 36)`` but produces
        # non-standard UUID strings (missing dashes), which fail D2
        # semantic verification. The Core ColumnMapper already maps
        # ``uuid``/``guid``/``token`` column names to the ``uuid``
        # generator, but only when ``generator`` is empty — when the
        # LLM explicitly picked ``pattern``, the semantic match is
        # skipped. This upgrade is conservative: it only fires when
        # the column has no LIKE constraint (LIKE-constrained columns
        # have a specific format that ``uuid`` cannot satisfy) and
        # the column is in source mode (no ``derive_from``).
        # Decision test: any database with a ``*_uuid`` column benefits.
        if has_derive or gen is None or gen == "uuid" or meta is None:
            return gen
        if "uuid" in c.get("name", "").lower() and not _has_like_constraint(c.get("name", ""), meta.constraints):
            gen = "uuid"
            c["generator"] = "uuid"
            c.pop("params", None)
        return gen

    def _repair_uuid_primary_generator(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool
    ) -> Any:
        meta = context.meta

        # UUID type + autoincrement mismatch: when the column's SQL type
        # is UUID (e.g., PostgreSQL ``id UUID DEFAULT gen_random_uuid()``)
        # and the LLM picked ``autoincrement`` (which produces integers),
        # the fill crashes with ``cannot cast type integer to uuid``.
        # The LLM picks ``autoincrement`` because the column is a PK, but
        # UUID PKs with DEFAULT gen_random_uuid() are not autoincrement in
        # the traditional SERIAL sense. Fix by upgrading to ``uuid``
        # generator, which produces valid UUID v4 strings.
        # Decision test: any PostgreSQL database with UUID PK columns.
        if (
            not has_derive
            and gen == "autoincrement"
            and meta is not None
            and meta.column_types.get(c.get("name", ""), "").upper() == "UUID"
        ):
            gen = "uuid"
            c["generator"] = "uuid"
            c.pop("params", None)
        return gen

    def _repair_string_check_generator(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool
    ) -> Any:
        meta = context.meta

        # Semantic downgrade detection: the LLM sometimes picks a
        # generic generator (``string``, ``catch_phrase``) for a
        # column whose name matches a Core ColumnMapper
        # EXACT_MATCH_RULES key that maps to a more specific
        # semantic generator. For example:
        #   - ``country_code`` → LLM picks ``string`` with
        #     min_length=2, max_length=2 → produces random 2-char
        #     strings like 'le', 'yb', 'OQ' instead of real ISO
        #     country codes like 'US', 'CN', 'GB'.
        #   - ``email`` → LLM picks ``string`` → produces gibberish
        #     instead of valid email addresses.
        #   - ``url`` → LLM picks ``string`` → produces random text
        #     instead of valid URLs.
        #
        # This safety net detects such downgrades and upgrades the
        # generator to the semantic one from EXACT_MATCH_RULES. It
        # only fires when:
        #   - column is in source mode (no ``derive_from``)
        #   - LLM picked a generic text generator (``string``,
        #     ``catch_phrase``)
        #   - column name matches an EXACT_MATCH_RULES key
        #   - the matched generator is NOT also generic (i.e., more
        #     specific than ``string``/``catch_phrase``/``sentence``/
        #     ``text``)
        #   - column has no LIKE constraint (LIKE-constrained columns
        #     need a ``pattern`` generator)
        #
        # CHECK-constrained columns (e.g., ``country_code IN
        # ('US','CN')``) are handled by the re-infer params path
        # below, which fires AFTER this safety net and overrides
        # with a ``choice`` generator if an IN constraint exists.
        # So the order is: semantic upgrade first, then CHECK
        # constraint inference can override if needed.
        #
        # Decision test: any database with semantic column names
        # (country_code, email, url, phone, etc.) where the LLM
        # downgraded them to generic strings benefits.
        if not has_derive and generator_name(gen) in {"string", "catch_phrase"} and meta is not None:
            col_name_sd = c.get("name", "").lower()
            if col_name_sd and not _has_like_constraint(c.get("name", ""), meta.constraints):
                mapper_sd = _get_column_mapper()
                semantic_gen = mapper_sd.EXACT_MATCH_RULES.get(col_name_sd)
                # Only upgrade if the semantic generator is more
                # specific than the current generic one. Generic
                # text generators produce random text that doesn't
                # match the column's semantic intent.
                generic_text_gens = {"string", "catch_phrase", "sentence", "text"}
                if semantic_gen and semantic_gen not in generic_text_gens:
                    c["generator"] = semantic_gen
                    # Apply EXACT_MATCH_PARAMS if available (e.g.,
                    # ``latitude`` has min/max_value from
                    # EXACT_MATCH_PARAMS).
                    if semantic_params := mapper_sd.EXACT_MATCH_PARAMS.get(col_name_sd, {}):
                        c["params"] = dict(semantic_params)
                    else:
                        c["params"] = {}
                    gen = semantic_gen
        return gen

    def _repair_fixed_length_semantic_generator(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool
    ) -> Any:
        meta = context.meta
        table_name = context.table_name

        # Table-context-aware name → entity-appropriate generator: the
        # Core ColumnMapper maps ``name`` → ``name`` (person name
        # generator) via L3 exact match. This is correct for people
        # tables (customers, users, employees) but wrong for entity
        # tables where the name should be a business entity name.
        # Different entity types need different generators:
        #   - brands/stores → ``company`` (real company names like
        #     "Apple", "Samsung" — not catch phrases like "Adaptive
        #     3rdgeneration matrix" which no frontend would display
        #     as a brand name)
        #   - categories → ``word`` (simple nouns like "Electronics",
        #     "Books" — not multi-word catch phrases)
        #   - products and other entities → ``catch_phrase`` (multi-
        #     word descriptive phrases are acceptable for products)
        if (
            not has_derive
            and generator_name(gen) in {"name", "catch_phrase", "template"}
            and meta is not None
            and (col_name_ctx := c.get("name", "")) == "name"
        ):
            tbl_lower = table_name.lower()
            # Entity table patterns: tables whose ``name`` column
            # represents a business entity name, not a person name.
            entity_table_patterns = (
                "product",
                "store",
                "shop",
                "brand",
                "categor",
                "warehouse",
                "supplier",
                "vendor",
                "course",
                "project",
                "asset",
                "equip",
                "depart",
                "module",
                "menu",
                "page",
                "topic",
                "channel",
                "plan",
            )
            if any(p in tbl_lower for p in entity_table_patterns):
                # Locale-aware entity name generation.
                # ``catch_phrase`` does NOT support zh_CN locale —
                # Faker silently falls back to English output, which
                # is semantically wrong for a Chinese-locale YAML
                # (brands.name showing "Reactive upward-trending
                # capability" instead of a Chinese brand name).
                # When the locale is zh_CN and the name column is
                # UNIQUE, use ``template`` with a Chinese prefix so
                # the generated names are guaranteed unique AND
                # locale-appropriate (e.g., ``品牌0001``).
                gen = self._choose_entity_name_generator(context, c, gen, col_name_ctx, tbl_lower)
        return gen

    def _repair_unique_template_generator(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool
    ) -> Any:
        config = context.config
        req_digits = context.req_digits
        table_name = context.table_name

        # NAME- template on non-code columns → catch_phrase: the LLM
        # sometimes generates ``template: NAME-{sequence:04d}`` for
        # entity name columns (e.g., brands.name, categories.name)
        # instead of using ``catch_phrase``. The ``NAME-`` prefix is
        # a person-name placeholder — semantically wrong for product
        # /brand/category names. This safety net detects such templates
        # on ``name`` columns and replaces them with ``catch_phrase``.
        # Decision test: any database where the LLM used a NAME-
        # template for an entity name column benefits.
        if not has_derive and gen == "template":
            tmpl_params = c.get("params", {})
            tmpl_str = tmpl_params.get("template", "") if isinstance(tmpl_params, dict) else ""
            if isinstance(tmpl_str, str) and tmpl_str.startswith("NAME-") and (c.get("name", "")) == "name":
                # Locale-aware: zh_CN should not use catch_phrase
                # (English-only under zh_CN locale).
                cur_locale_nm = config.get("locale", "en_US") or "en_US"
                if cur_locale_nm.lower().startswith("zh"):
                    tbl_lower_nm = table_name.lower()
                    _zh_prefix = "名称"
                    if any(p in tbl_lower_nm for p in ("brand", "store", "shop")):
                        _zh_prefix = "品牌"
                    elif "categor" in tbl_lower_nm:
                        _zh_prefix = "分类"
                    elif "product" in tbl_lower_nm:
                        _zh_prefix = "产品"
                    c["generator"] = "template"
                    c["params"] = {"template": f"{_zh_prefix}{{sequence:0{req_digits}d}}"}
                    gen = "template"
                else:
                    c["generator"] = "catch_phrase"
                    c.pop("params", None)
                    c["params"] = {}
                    gen = "catch_phrase"
        return gen

    def _repair_phone_bounds(self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool) -> None:
        meta = context.meta

        # Phone country_code stripping: when a phone column has a
        # ``LENGTH(phone) = 11`` CHECK constraint (Chinese mobile
        # format), the ``country_code: true`` param would prepend
        # ``+86 `` making the phone 15 chars — violating the CHECK.
        # Strip ``country_code`` to ensure the phone generator
        # produces the raw 11-digit Chinese mobile number.
        # Decision test: any database with ``LENGTH(phone) = 11``
        # CHECK constraint where the LLM added ``country_code: true``
        # benefits — without this, fill fails with
        # ``CHECK constraint failed: LENGTH(phone) = 11``.
        if not has_derive and gen == "phone" and meta is not None:
            phone_params = c.get("params", {})
            if isinstance(phone_params, dict) and phone_params.get("country_code"):
                col_name_ph = c.get("name", "")
                for ctr in meta.constraints:
                    if ctr.get("type") != "check":
                        continue
                    ctr_expr = ctr.get("expression", "")
                    # Check if this CHECK constrains this phone column to 11
                    if (
                        isinstance(ctr_expr, str)
                        and "LENGTH" in ctr_expr
                        and col_name_ph in ctr_expr
                        and "=11" in ctr_expr.replace(" ", "")
                        and _is_phone_like(col_name_ph)
                    ):
                        c["params"] = {}
                        break

    def _repair_unconstrained_fk_fallback(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool
    ) -> Any:
        meta = context.meta

        # Non-FK business identifier → template: columns like
        # ``transaction_id`` are matched by the L5 pattern ``.*_id$``
        # → ``foreign_key_or_integer``, but they are NOT foreign keys
        # — they are third-party business identifiers (e.g., payment
        # gateway transaction numbers). This safety net detects non-FK
        # ``*_id`` columns with known business-identifier names and
        # upgrades them to ``template`` generators producing realistic
        # business ID formats (e.g., ``TXN-{sequence:08d}``).
        # Decision test: any database with transaction_id/payment_ref
        # columns that are NOT foreign keys benefits — without this,
        # the column gets random integers that don't look like real
        # transaction numbers.
        if not has_derive and gen == "foreign_key_or_integer" and meta is not None:
            col_name_biz = c.get("name", "").lower()
            biz_id_templates = {
                "transaction_id": "TXN-{sequence:08d}",
                "txn_id": "TXN-{sequence:08d}",
                "payment_ref": "PAY-{sequence:08d}",
                "reference_no": "REF-{sequence:08d}",
                "tracking_no": "TRK-{sequence:010d}",
            }
            if col_name_biz in biz_id_templates:
                # Build FK set for this table to confirm the column
                # is NOT an actual foreign key.
                fk_cols_biz: set[str] = set()
                for fk_biz in meta.foreign_keys:
                    for fc_biz in fk_biz.get("columns", []):
                        fk_cols_biz.add(fc_biz)
                if col_name_biz not in fk_cols_biz:
                    c["generator"] = "template"
                    c["params"] = {"template": biz_id_templates[col_name_biz]}
                    gen = "template"
        return gen

    def _repair_pattern_length(self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool) -> Any:
        meta = context.meta

        # Phone pattern → Chinese mobile regex: the LLM sometimes
        # picks ``generator: pattern`` with ``regex: [0-9]{11}`` for
        # phone columns with ``LENGTH(phone) = 11`` CHECK constraints.
        # While this satisfies the CHECK (11 random digits), it
        # produces non-realistic numbers like ``76757304493`` that
        # don't start with 1 (Chinese mobile numbers MUST start with
        # 1[3-9]). Replace with the Chinese mobile regex
        # ``^1[3-9]\d{9}$`` to produce realistic numbers.
        # Note: we do NOT switch to the ``phone`` generator because
        # faker's zh_CN phone_number() includes dashes/spaces that
        # violate LENGTH=11 (e.g., "138-1234-5678" has LENGTH=13).
        if not has_derive and gen == "pattern" and meta is not None:
            col_name_ph = c.get("name", "")
            if _is_phone_like(col_name_ph):
                for ctr in meta.constraints:
                    if ctr.get("type") != "check":
                        continue
                    ctr_expr = ctr.get("expression", "")
                    if (
                        isinstance(ctr_expr, str)
                        and "LENGTH" in ctr_expr
                        and col_name_ph in ctr_expr
                        and "=11" in ctr_expr.replace(" ", "")
                    ):
                        c["generator"] = "pattern"
                        c["params"] = {"regex": r"^1[3-9]\d{9}$"}
                        gen = "pattern"
                        break
        return gen

    def _normalize_currency_precision(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool, _col_name_lower: str
    ) -> None:
        if has_derive and any(k in _col_name_lower for k in _CURRENCY_NAME_KEYWORDS):
            expr = c.get("expression", "")
            if isinstance(expr, str) and expr and not expr.startswith("round(") and "row[" not in expr:
                c["expression"] = f"round({expr}, 2)"

        # Non-derive currency float → precision: 2: ``float`` generators
        # without ``precision`` produce values like ``28012.8`` (1dp)
        # or ``63896.9`` instead of ``28012.80`` / ``63896.90``. Real
        # frontend forms always send currency values with 2 decimal
        # places. This safety net adds ``precision: 2`` to non-derive
        # float columns whose name matches currency-related keywords.
        # Decision test: any non-derive ``float`` column with a currency-
        # related name benefits — without this, the database stores
        # inconsistent decimal places that no real frontend would submit.
        if not has_derive and gen == "float" and any(k in _col_name_lower for k in _CURRENCY_NAME_KEYWORDS):
            cur_params = c.get("params")
            if isinstance(cur_params, dict) and "precision" not in cur_params:
                cur_params["precision"] = 2

    def _tighten_numeric_bounds(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool, _col_name_lower: str
    ) -> None:
        table_name = context.table_name

        # Semantic max_value cap: integer/float columns whose CHECK
        # constraint only sets a lower bound (e.g., ``sort_order >= 0``)
        # or a very high upper bound (e.g., ``quantity <= 999``) end up
        # with huge generated values like sort_order=704134 or
        # carts.quantity=820. Real frontends never submit such values
        # — sort_order inputs are 0-999, cart quantity inputs are 1-99,
        # loyalty points are 0-100k. This safety net caps max_value for
        # known semantic column names, but only if the current
        # max_value is missing or larger than the semantic cap (never
        # increases an existing smaller max_value).
        # Decision test: any database with these column names benefits
        # — without this, the database stores values that no real
        # frontend form would ever submit.
        if not has_derive and generator_name(gen) in CANONICAL_NUMERIC_GENERATORS:
            semantic_max_values: dict[str, int | float] = {
                "sort_order": 999,
                "points_balance": 100000,
                "balance_after": 100000,
                "stock_qty": 10000,
                "low_stock_threshold": 100,
                "total_spent": 999999.99,
                "refunded_qty": 99,
                "weight_kg": 99.99,
            }
            # Cart/order quantity: CHECK often allows up to 999, but
            # real frontend forms cap at 99.
            if (_col_name_lower == "quantity" and "cart" in table_name.lower()) or (
                _col_name_lower == "quantity" and "order_item" in table_name.lower()
            ):
                semantic_max_values["quantity"] = 99
            if _col_name_lower in semantic_max_values:
                _sem_max = semantic_max_values[_col_name_lower]
                cur_params_sem = c.get("params")
                if isinstance(cur_params_sem, dict):
                    _cur_max = cur_params_sem.get("max_value")
                    if _cur_max is None or _cur_max > _sem_max:
                        cur_params_sem["max_value"] = _sem_max

    def _limit_integer_scale(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool, _col_name_lower: str
    ) -> Any:
        meta = context.meta

        # REAL column type → float generator (not integer): when the
        # database column type is REAL/FLOAT/DOUBLE and the LLM
        # picked ``integer``, the generated values are whole numbers
        # (e.g., cost_price=28013) which no real frontend would
        # submit for a price field. This safety net converts
        # ``integer`` to ``float`` for REAL-type columns, preserving
        # any existing min_value/max_value and adding precision: 2
        # for currency-named columns.
        # Decision test: any REAL column with ``integer`` generator
        # benefits — without this, price/amount columns store whole
        # numbers instead of decimals.
        if (
            not has_derive
            and gen == "integer"
            and meta is not None
            and (col_name_rt := c.get("name", "")) in meta.column_types
        ):
            col_type_rt = meta.column_types.get(col_name_rt, "")
            base_type_rt = re.sub(r"\(.*\)", "", col_type_rt.upper()).strip()
            if base_type_rt in {"REAL", "FLOAT", "DOUBLE", "DOUBLE PRECISION", "NUMERIC", "DECIMAL"}:
                c["generator"] = "float"
                gen = "float"
                # Preserve existing params, add precision for currency cols
                cur_params_rt = c.get("params")
                if not isinstance(cur_params_rt, dict):
                    cur_params_rt = {}
                    c["params"] = cur_params_rt
                if any(k in _col_name_lower for k in _CURRENCY_NAME_KEYWORDS) and "precision" not in cur_params_rt:
                    cur_params_rt["precision"] = 2
        return gen

    def _default_coupon_null_ratio(
        self, context: _ColumnRuleContext, c: dict[str, Any], has_derive: bool, _col_name_lower: str
    ) -> None:
        meta = context.meta

        # coupon_code null_ratio: coupon codes are optional — real
        # orders rarely have a coupon applied (typically 10-30% of
        # orders). Without null_ratio, the template generator
        # produces a coupon for 100% of orders, which is business-
        # incorrect. This safety net adds null_ratio: 0.8 (80% NULL)
        # to coupon_code columns that are nullable and don't already
        # have null_ratio set.
        # Decision test: any table with a nullable ``coupon_code``
        # column benefits — without this, every order has a coupon.
        if not has_derive and _col_name_lower == "coupon_code" and "null_ratio" not in c and meta is not None:
            col_name_cc = c.get("name", "")
            # Check column is nullable (not NOT NULL)
            nullable_cc = True
            for col_info_cc in getattr(meta, "columns_info", []):
                if getattr(col_info_cc, "name", "") == col_name_cc:
                    nullable_cc = getattr(col_info_cc, "nullable", True)
                    break
            if nullable_cc:
                c["null_ratio"] = 0.8

    def _derive_variant_value(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool, _col_name_lower: str
    ) -> bool:
        tcfg = context.tcfg

        # variant_value → derive_from variant_name: in e-commerce
        # schemas, ``variant_name`` (Color/Size/Material) and
        # ``variant_value`` (Red/Large/Cotton) must be semantically
        # correlated. Without this, independent random choices produce
        # nonsensical combinations like variant_name=Material +
        # variant_value=Medium (Medium is a Size, not a Material).
        # This safety net detects tables with both columns and sets
        # ``variant_value`` to derive_from ``variant_name`` with a
        # conditional expression that picks domain-appropriate values.
        if not has_derive and _col_name_lower == "variant_value" and gen == "choice":
            has_variant_name = any(col.get("name", "").lower() == "variant_name" for col in tcfg.get("columns", []))
            if has_variant_name:
                c["generator"] = None
                c.pop("generator", None)
                c.pop("params", None)
                c["derive_from"] = "variant_name"
                c["expression"] = (
                    "['Red','Blue','Black','White','Green'][random_int(0,4)] "
                    "if value == 'Color' else "
                    "(['Large','Medium','Small'][random_int(0,2)] "
                    "if value == 'Size' else "
                    "(['Cotton','Leather','Wood','Metal','Plastic'][random_int(0,4)] "
                    "if value == 'Material' else "
                    "(['Pro','Standard','Classic','Modern'][random_int(0,3)] "
                    "if value == 'Style' else "
                    "(['V1','V2','V3','Pro','Standard'][random_int(0,4)] "
                    "if value == 'Version' else "
                    "['128GB','256GB','512GB','1TB'][random_int(0,3)]))))"
                )
                has_derive = True
        return has_derive

    def _guard_inventory_movement_quantity(
        self, context: _ColumnRuleContext, c: dict[str, Any], has_derive: bool, _col_name_lower: str
    ) -> None:
        table_name = context.table_name

        # inventory_movements quantity sign: the LLM's expression
        # handles ``inbound`` (positive) and ``outbound`` (negative)
        # but leaves ``transfer_out`` and ``return`` with random signs.
        # In real warehouse logic:
        #   - transfer_in → positive (stock arriving)
        #   - transfer_out → negative (stock leaving)
        #   - return → positive (stock coming back from customer)
        # This safety net replaces the expression when the table is
        # ``inventory_movements`` and derive_from is ``movement_type``.
        if (
            has_derive
            and "inventory_movement" in table_name.lower()
            and _col_name_lower == "quantity"
            and c.get("derive_from") == "movement_type"
        ):
            c["expression"] = (
                "random_int(1, 100) if value == 'inbound' else "
                "(random_int(-100, -1) if value == 'outbound' else "
                "(random_int(1, 100) if value == 'transfer_in' else "
                "(random_int(-100, -1) if value == 'transfer_out' else "
                "(random_int(1, 100) if value == 'return' else "
                "(random_int(1, 100) if random_int(0, 1) == 0 else "
                "random_int(-100, -1))))))"
            )

    def _preserve_check_enum_generator(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool
    ) -> Any:
        meta = context.meta

        # PostgreSQL-specific type enforcement: the LLM doesn't
        # understand PG-specific types (INTERVAL, TSVECTOR, TSTZRANGE,
        # ARRAY) and picks generic generators that produce values
        # incompatible with the column type. For example:
        #   - INTERVAL needs a PG interval literal like "0 seconds",
        #     not an integer or datetime
        #   - TSVECTOR needs a tsvector literal, not a random string
        #   - TSTZRANGE needs a range literal like "empty", not a
        #     datetime
        #   - ARRAY (TEXT[], INTEGER[]) needs an array literal like
        #     "{}", not a string/integer
        # The LLM sees ``duration`` and picks ``integer`` (thinking
        # it's seconds); sees ``labor_time`` and picks ``datetime``
        # (because of the ``_time`` suffix); sees ``member_ids`` and
        # the L5 pattern ``.*_ids$`` picks ``json``. All produce
        # values that cause ``DataError`` at fill time.
        # We bypass ``map_column`` entirely and call
        # ``_type_faithful_fallback`` directly because ``map_column``
        # runs L5 (pattern match) before L9 (type fallback), and L5
        # would return ``json`` for ``*_ids`` or ``datetime`` for
        # ``*_time`` — both wrong for PG-specific types. The type
        # constraint is a hard physical constraint: you cannot
        # insert a string into an INTEGER[] column, so type-based
        # fallback must take priority over name-based matching.
        # This is conservative: it only fires for source-mode columns
        # (no ``derive_from``) and only for the known PG-specific
        # types.
        if (
            not has_derive
            and gen is not None
            and meta is not None
            and (col_name_pg := c.get("name", "")) in meta.column_types
        ):
            col_type_pg = meta.column_types.get(col_name_pg, "")
            base_type_pg = re.sub(r"\(.*\)", "", col_type_pg.upper()).strip()
            is_pg_array = base_type_pg.endswith("[]") or base_type_pg == "ARRAY"
            is_pg_specific = base_type_pg in {"INTERVAL", "TSVECTOR", "TSTZRANGE"}
            # ARRAY types: always override (the string '{}' from
            # choice generator doesn't work with PG parameterized
            # queries; null_ratio=1.0 is the safe fallback).
            # PG-specific types: override only when the LLM picked
            # a wrong generator (not already ``choice``).
            if is_pg_array or (is_pg_specific and gen != "choice"):
                spec = _get_column_mapper()._type_faithful_fallback(col_type_pg.upper())
                c["generator"] = spec.generator_name
                c["params"] = dict(spec.params)
                if spec.null_ratio > 0:
                    c["null_ratio"] = spec.null_ratio
                gen = spec.generator_name
        return gen

    def _recover_missing_template_params(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, params: Any
    ) -> Any:
        # Missing template param repair: LLM provides
        # ``generator: template`` but forgets the ``template``
        # param (e.g., ``params: {}``). Without a template string,
        # the template generator raises KeyError at fill time,
        # causing the entire table to fail (0 rows generated).
        # Fill in a default template using the column name prefix.
        if gen == "template" and not params.get("template"):
            col_name = c.get("name", "item")
            prefix = col_name.upper().split("_")[0][:10]
            params = {"template": f"{prefix}-{{sequence:04d}}"}
            c["params"] = params
        return params

    def _resize_sequence_template(self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, params: Any) -> None:
        req_digits = context.req_digits
        # Sequence format upgrade: when the template contains
        # ``{sequence:0Nd}`` with N < req_digits, upgrade to
        # ``{sequence:0{req_digits}d}``. The LLM sometimes emits
        # ``{sequence:03d}`` (3-digit zero-padding), but sequences
        # 1-999 fit 3 digits while 1000+ expands to 4 digits,
        # breaking format consistency within the column (e.g.,
        # ``user_001`` vs ``user_1000``). Dynamic digit width based
        # on table count avoids both under-padding and over-padding.
        # Only upgrade narrower formats — never downgrade wider ones.
        if gen == "template":
            tmpl = params.get("template")
            if isinstance(tmpl, str):
                # B023: req_digits 是外层 tables 循环变量，
                # 用默认参数在定义时绑定当前迭代的值。
                def _upgrade_seq(m: re.Match[str], digits: int = req_digits) -> str:
                    return f"{{sequence:0{digits}d}}" if int(m.group(1)) < digits else m.group(0)

                if (upgraded := re.sub(r"\{sequence:0(\d)d\}", _upgrade_seq, tmpl)) != tmpl:
                    params["template"] = upgraded
                    c["params"] = params

    def _repair_template_character_sets(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, params: Any
    ) -> None:
        # Template format cleanup: fix common LLM template mistakes.
        #   - Trailing dash/underscore before {sequence}: ``PRODUCT_-
        #     {sequence:04d}`` → ``PRODUCT-{sequence:04d}`` (the
        #     extra ``_`` produces ugly codes like ``PRODUCT_-0001``).
        #   - Double separators: ``STORE_CO-{sequence:04d}`` →
        #     ``STORE-{sequence:04d}`` (the ``_CO`` suffix is
        #     redundant when the column is already ``store_code``).
        #   - Trailing dash without separator: ``PAYMENT_-
        #     {sequence:04d}`` → ``PAYMENT-{sequence:04d}``
        # Decision test: any template with ``_-{sequence`` or
        # ``-{sequence`` preceded by ``_`` benefits.
        if gen == "template":
            tmpl_cl = params.get("template")
            if isinstance(tmpl_cl, str):
                cleaned = tmpl_cl
                # Fix ``X_-{sequence`` → ``X-{sequence``
                cleaned = cleaned.replace("_-{sequence", "-{sequence")
                # Fix ``X_-{`` (other placeholders) → ``X-{``
                if (cleaned := cleaned.replace("_-{", "-{")) != tmpl_cl:
                    params["template"] = cleaned
                    c["params"] = params

    def _infer_missing_column_generator(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool, params: Any
    ) -> Any:
        meta = context.meta
        if not gen and not has_derive:
            col_name = c.get("name", "")
            # Infer generator from params when possible
            if "min_length" in params or "max_length" in params:
                gen = "string"
            elif "choices" in params:
                gen = "choice"
            elif "template" in params:
                gen = "template"
            elif "min_value" in params or "max_value" in params:
                mv = params.get("min_value")
                sample = mv if mv is not None else params.get("max_value")
                gen = "float" if isinstance(sample, float) else "integer"
            elif meta and col_name in meta.columns:
                # Delegate to Core ColumnMapper for semantic name
                # matching (same fix as Step 4 in
                # _build_subgraph_config). When the LLM strips the
                # generator field AND no params are available to
                # infer from, the previous code used
                # _placeholder_generator(col_type) which returned
                # "string" for ALL TEXT columns — producing random
                # gibberish for email, username, avatar_url, etc.
                # Using ColumnMapper ensures semantic generators are
                # picked even in this post-LLM repair path.
                col_type = meta.column_types.get(col_name, "TEXT")
                col_info = ColumnInfo(
                    name=col_name,
                    type=col_type,
                    nullable=True,
                    default=None,
                    is_primary_key=False,
                    is_autoincrement=False,
                )
                spec = _get_column_mapper().map_column(col_info)
                if (gen := spec.generator_name) == "skip":
                    gen = _placeholder_generator(col_type)
                if gen == "string" and _is_date_column(col_name):
                    gen = "datetime"
            if gen:
                c["generator"] = gen
        return gen

    def _reapply_single_column_checks(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool, params: Any
    ) -> tuple[Any, Any]:
        meta = context.meta

        # Re-infer params from CHECK constraints when the LLM strips
        # them. The LLM sometimes returns ``params: {}`` for columns
        # that have range CHECKs (e.g., ``latitude >= -90.0 AND
        # latitude <= 90.0``), causing fill-time CHECK violations.
        # Re-run the deterministic single-column inference to recover
        # the bounds. Applied when:
        #   - column is in source mode (no ``derive_from``)
        #   - LLM provided a generator (with or without params)
        # Outcomes:
        #   1. inferred generator matches current → apply inferred params
        #      (e.g., both agree on ``integer``, recover min/max_value)
        #   2. inferred generator is ``boolean`` or ``choice`` (from an
        #      ``IN (...)`` constraint) but current is different →
        #      override BOTH generator and params. The ``IN`` constraint
        #      is very specific: ``col IN (0, 1)`` MUST use ``boolean``,
        #      ``col IN ('a', 'b')`` MUST use ``choice``. An ``integer``
        #      generator would produce values outside the allowed set.
        #   3. column has a LIKE CHECK constraint → override with
        #      ``pattern`` generator (only ``pattern`` can guarantee
        #      the format).
        #   4. IN-constraint override: when both current and inferred
        #      generators are ``choice`` but the current choices don't
        #      match the IN-constraint values (e.g., L3 exact match
        #      gave ``choices: [0, 1]`` but CHECK says
        #      ``status IN ('active', 'inactive', ...)``), the IN
        #      constraint takes priority — it's a hard database
        #      constraint, not a heuristic. Without this override,
        #      every ``status`` column in PostgreSQL tables with
        #      string IN constraints would fail at fill time because
        #      the L3 exact match ``choices: [0, 1]`` produces integers
        #      that violate ``CHECK (status IN ('active', ...))``.
        if not has_derive and gen and meta is not None and (col_name := c.get("name", "")) in meta.columns:
            # Upgrade integer→float when the column type is
            # REAL/FLOAT but the LLM picked ``integer`` (e.g.,
            # ``interest_rate REAL CHECK (interest_rate >= 0.0
            # AND interest_rate <= 0.5)`` — LLM sets
            # ``generator: integer, max_value: 100``, violating
            # the CHECK at fill time). This upgrade must happen
            # BEFORE _infer_from_check_constraints so the
            # ``inf_gen == gen`` check in Case 5 below can match
            # (inf_gen is ``float`` because the CHECK literals
            # are floats like ``0.0``, ``0.5``).
            gen, params = self._upgrade_checked_float_generator(meta, c, gen, params, col_name)
            if (inferred := _infer_from_check_constraints(col_name, meta.constraints, meta.columns)) is not None:
                inf_gen, inf_params = inferred
                if inf_gen == gen and inf_params and not params:
                    # Case 1: generators agree AND current params
                    # are empty — apply inferred params. Only
                    # fires when params is empty to avoid
                    # replacing L3 exact match params (e.g.,
                    # ``quantity`` has ``min_value: 1,
                    # max_value: 100`` from L3; CHECK
                    # ``quantity > 0`` would infer only
                    # ``min_value: 1``, losing ``max_value``).
                    c["params"] = inf_params
                    params = inf_params
                elif inf_gen in {"boolean", "choice"} and gen != inf_gen:
                    # Case 2: LLM picked wrong generator for an
                    # IN-constrained column. Override with the
                    # correct boolean/choice generator.
                    c["generator"] = inf_gen
                    c["params"] = inf_params
                    gen = inf_gen
                    params = inf_params
                elif inf_gen == "pattern" and _has_like_constraint(col_name, meta.constraints):
                    # Case 3: column has a LIKE CHECK constraint
                    # (e.g., ``start_time LIKE '__:__'``). Only a
                    # ``pattern`` generator can guarantee the
                    # format — ``datetime``/``string`` generators
                    # produce values that violate the LIKE CHECK.
                    c["generator"] = inf_gen
                    c["params"] = inf_params
                    gen = inf_gen
                    params = inf_params
                elif inf_gen == "choice" and gen == "choice" and inf_params and "choices" in inf_params:
                    # Case 4: IN-constraint override. Both
                    # generators are ``choice`` but the current
                    # choices (from L3 exact match or LLM) don't
                    # match the IN-constraint values. The IN
                    # constraint is authoritative — override.
                    # Example: L3 gives ``choices: [0, 1]`` but
                    # CHECK says ``status IN ('active', ...)``.
                    c["params"] = inf_params
                    params = inf_params
                elif inf_gen == gen and inf_params and params:
                    # Case 5: LLM provided params that CONFLICT
                    # with CHECK constraints. The LLM may set
                    # min_value/max_value that violate the CHECK
                    # (e.g., ``min_value: 0`` when CHECK requires
                    # ``>= 60 AND <= 250``). The CHECK constraint
                    # is authoritative — override conflicting
                    # bounds with the CHECK-inferred values.
                    # Non-conflicting bounds are preserved (e.g.,
                    # if LLM set ``max_value: 200`` and CHECK
                    # allows ``<= 250``, keep 200).
                    params = self._merge_authoritative_numeric_bounds(c, inf_params, params)
        return gen, params

    def _restore_cross_column_derivation(
        self, context: _ColumnRuleContext, c: dict[str, Any], has_derive: bool
    ) -> bool:
        meta = context.meta

        # Cross-column derive_from restoration: when the LLM is called
        # to heal one column, it sometimes rewrites OTHER columns in
        # the same table — replacing a ``derive_from`` config (correctly
        # inferred by ``_build_subgraph_config`` Step 1) with a plain
        # ``generator`` (e.g., ``closed_at`` getting ``generator:
        # datetime`` instead of ``derive_from: opened_at``). This
        # causes CHECK violations at fill time because the plain
        # generator ignores the cross-column ordering constraint
        # (e.g., ``closed_at IS NULL OR closed_at >= opened_at``
        # is violated 50% of the time with random datetimes).
        #
        # Fix: re-apply ``_infer_cross_column_config`` for columns
        # that (a) have a cross-column CHECK constraint, (b) do NOT
        # currently have ``derive_from``. The re-inferred derive_from
        # takes priority over the LLM's plain generator because it
        # guarantees CHECK compliance.
        #
        # The old guard ``c.get("null_ratio", 0) < 1.0`` was removed
        # because it prevented Pattern 4a (``col IS NULL OR col =
        # col1 * col2``) from overriding an LLM-set ``null_ratio=1.0``.
        # Pattern 4a returns ``derive_from`` + ``null_ratio=0.3``,
        # which produces realistic data (70% computed, 30% NULL)
        # instead of all-NULLs. To still respect columns that SHOULD
        # be all-NULL (e.g., Pattern 35 date columns), we check
        # ``cross_result.get("null_ratio", 0.0) < 1.0`` AFTER
        # inference — if the deterministic code also wants
        # ``null_ratio=1.0``, we don't override.
        if not has_derive and meta is not None and (col_name := c.get("name", "")) in meta.columns:
            col_type = meta.column_types.get(col_name, "TEXT")
            # Rebuild fk_cols_set for this table (needed by
            # _infer_cross_column_config for Pattern 30).
            fk_cols_set_55: set[str] = set()
            for fk in meta.foreign_keys:
                for fc in fk.get("columns", []):
                    fk_cols_set_55.add(fc)
            cross_result = _infer_cross_column_config(
                col_name,
                meta.constraints,
                meta.columns,
                col_type,
                fk_cols_set_55,
                column_types=meta.column_types,
            )
            if cross_result is not None and "derive_from" in cross_result and cross_result.get("null_ratio", 0.0) < 1.0:
                # Restore derive_from — remove any source-mode keys
                # that the LLM set (generator, params, null_ratio,
                # provider) to avoid Pydantic ValidationError
                # (mutual exclusivity: derive_from + null_ratio is
                # invalid). ``null_ratio`` MUST be popped because
                # the LLM may have set it to 1.0, and leaving it
                # alongside ``derive_from`` would cause a
                # ValidationError at config load time.
                c.pop("generator", None)
                c.pop("params", None)
                c.pop("null_ratio", None)
                c.pop("provider", None)
                c.update(cross_result)
                has_derive = True
        return has_derive

    def _preserve_unique_exact_length(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, has_derive: bool, params: Any
    ) -> tuple[Any, Any]:
        meta = context.meta

        # UNIQUE + LENGTH(col) = N safety net:
        # Even if the LLM correctly provided ``string`` with
        # min_length=N, max_length=N, the unique adjuster will
        # increase max_length to guarantee uniqueness, breaking the
        # CHECK constraint. Convert to ``pattern`` with
        # ``[A-Za-z0-9]{N}`` which the unique adjuster does NOT
        # touch (uniqueness handled by ConstraintSolver backtracking).
        if not has_derive and gen == "string" and meta is not None and (col_name := c.get("name", "")) in meta.columns:
            unique_cols_set = _get_unique_columns(meta.constraints)
            if (
                col_name in unique_cols_set
                and (exact_n := _get_exact_length_check(col_name, meta.constraints)) is not None
            ):
                c["generator"] = "pattern"
                c["params"] = {"regex": f"[A-Za-z0-9]{{{exact_n}}}"}
                gen = "pattern"
                params = c["params"]
        return gen, params

    def _collect_direct_date_requirements(self, meta: TableMeta) -> dict[str, tuple[str, set[str]]]:
        _direct_reqs: dict[str, tuple[str, set[str]]] = {}
        for ctr in meta.constraints:
            if ctr.get("type") != "check":
                continue
            expr_sm = ctr.get("expression", "")
            if not isinstance(expr_sm, str):
                continue
            # Match: col1 != 'VALUE' OR date_col IS NOT NULL
            m_sm = re.match(
                r"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+(\w+)\s+IS\s+NOT\s+NULL\s*$",
                expr_sm,
                re.IGNORECASE,
            )
            if m_sm:
                status_col_sm = m_sm.group(1)
                status_val_sm = m_sm.group(2)
                if (date_col_sm := m_sm.group(3)) not in _direct_reqs:
                    _direct_reqs[date_col_sm] = (status_col_sm, set())
                _direct_reqs[date_col_sm][1].add(status_val_sm)
        return _direct_reqs

    def _collect_date_dependency_graph(self, meta: TableMeta) -> dict[str, str]:
        _date_deps: dict[str, str] = {}  # date_col2 -> date_col1
        for ctr in meta.constraints:
            if ctr.get("type") != "check":
                continue
            expr_dep = ctr.get("expression", "")
            if not isinstance(expr_dep, str):
                continue
            m_dep = re.match(
                r"^\s*(\w+)\s+IS\s+NULL\s+OR\s+\w+\s*>=\s*(\w+)\s*$",
                expr_dep,
                re.IGNORECASE,
            )
            if m_dep:
                dep_col = m_dep.group(1)  # date_col2 (the one with IS NULL)
                src_col = m_dep.group(2)  # date_col1 (the source)
                _date_deps[dep_col] = src_col
        return _date_deps

    def _choose_entity_name_generator(
        self, context: _ColumnRuleContext, c: dict[str, Any], gen: Any, col_name_ctx: str, tbl_lower: str
    ) -> Any:
        config = context.config
        req_digits = context.req_digits
        meta = context.meta
        cur_locale = config.get("locale", "en_US") or "en_US"
        _is_zh = cur_locale.lower().startswith("zh")
        # Brand/store names are company names — frontends
        # display them as "Nike", "Apple Store", not as
        # "Reactive upward-trending capability".
        company_table_patterns = (
            "brand",
            "store",
            "shop",
            "supplier",
            "vendor",
            "merchant",
            "retailer",
        )
        if any(p in tbl_lower for p in company_table_patterns):
            _unique_cols_comp = _get_unique_columns(meta.constraints) if meta else set()
            if col_name_ctx in _unique_cols_comp:
                if _is_zh:
                    # zh_CN + UNIQUE: template with Chinese
                    # prefix guarantees uniqueness without
                    # relying on catch_phrase (English-only).
                    c["generator"] = "template"
                    c["params"] = {"template": f"品牌{{sequence:0{req_digits}d}}"}
                    gen = "template"
                else:
                    # en_US + UNIQUE: catch_phrase has high
                    # entropy and supports English locale.
                    c["generator"] = "catch_phrase"
                    c["params"] = {}
                    gen = "catch_phrase"
            else:
                # Non-UNIQUE: company() supports zh_CN and
                # produces realistic Chinese company names.
                c["generator"] = "company"
                c["params"] = {}
                gen = "company"
        # Category names are simple nouns — frontends
        # display them as "Electronics", "Books", not as
        # "Centralized optimizing knowledgebase".
        elif "categor" in tbl_lower:
            _unique_cols_cat = _get_unique_columns(meta.constraints) if meta else set()
            if col_name_ctx in _unique_cols_cat:
                if _is_zh:
                    # zh_CN + UNIQUE: Chinese-prefixed
                    # template guarantees uniqueness.
                    c["generator"] = "template"
                    c["params"] = {"template": f"分类{{sequence:0{req_digits}d}}"}
                    gen = "template"
                else:
                    c["generator"] = "catch_phrase"
                    c["params"] = {}
                    gen = "catch_phrase"
            else:
                # word() supports zh_CN (returns Chinese
                # words like "电子", "图书").
                c["generator"] = "word"
                c["params"] = {}
                gen = "word"
        else:
            # products and other entities
            _unique_cols_ent = _get_unique_columns(meta.constraints) if meta else set()
            if col_name_ctx in _unique_cols_ent and _is_zh:
                c["generator"] = "template"
                c["params"] = {"template": f"产品{{sequence:0{req_digits}d}}"}
                gen = "template"
            else:
                c["generator"] = "catch_phrase"
                c["params"] = {}
                gen = "catch_phrase"
        return gen

    def _upgrade_checked_float_generator(
        self, meta: TableMeta, c: dict[str, Any], gen: Any, params: Any, col_name: str
    ) -> tuple[Any, Any]:
        col_type_ri = meta.column_types.get(col_name, "") if hasattr(meta, "column_types") else ""
        if (
            gen == "integer"
            and col_type_ri
            and any(k in col_type_ri.upper() for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC"))
        ):
            gen = "float"
            c["generator"] = "float"
            # Convert integer params to float equivalents
            if params:
                new_params_f = dict(params)
                for k_f in ("min_value", "max_value"):
                    if k_f in new_params_f and isinstance(new_params_f[k_f], int):
                        new_params_f[k_f] = float(new_params_f[k_f])
                c["params"] = new_params_f
                params = new_params_f
        return gen, params

    def _merge_authoritative_numeric_bounds(self, c: dict[str, Any], inf_params: dict[str, Any], params: Any) -> Any:
        if "min_value" in inf_params or "max_value" in inf_params:
            inf_min = inf_params.get("min_value")
            inf_max = inf_params.get("max_value")
            llm_min = params.get("min_value")
            llm_max = params.get("max_value")
            conflict = False
            new_params = dict(params)
            if inf_min is not None and (llm_min is None or llm_min < inf_min):
                new_params["min_value"] = inf_min
                conflict = True
            if inf_max is not None and (llm_max is None or llm_max > inf_max):
                new_params["max_value"] = inf_max
                conflict = True
            if conflict:
                c["params"] = new_params
                params = new_params
        return params

    def _collect_real_arithmetic_columns(
        self, columns_r: list[dict[str, Any]], meta_r: TableMeta
    ) -> list[dict[str, Any]]:
        real_derived_cols_r: list[dict[str, Any]] = []
        for c_r in columns_r:
            col_name_r = c_r.get("name", "")
            if "derive_from" not in c_r:
                continue
            if col_name_r not in meta_r.column_types:
                continue
            col_type_r = meta_r.column_types.get(col_name_r, "")
            if (re.sub(r"\(.*\)", "", col_type_r.upper()).strip()) != "REAL":
                continue
            expr_r = str(c_r.get("expression", ""))
            # Detect arithmetic on value or row[] refs (but not in
            # function names like abs(), random_float())
            if re.search(r"\bvalue\s*[\*\+\-]|[\*\+\-]\s*row\[|[\*\+\-]\s*abs\(", expr_r):
                real_derived_cols_r.append(c_r)
        return real_derived_cols_r

    def _stabilize_real_source_column(self, col_map_r: dict[str, dict[str, Any]], src_name_r: str) -> None:
        if (src_col_r := col_map_r.get(src_name_r)) is None:
            return
        src_gen_r = src_col_r.get("generator")
        src_params_r = src_col_r.get("params") or {}
        # Convert ALL float generators (with or without precision)
        # to integer. Fractional float values cause REAL (32-bit)
        # precision mismatches in arithmetic equality CHECKs:
        # Python computes in 64-bit float, PostgreSQL validates in
        # 32-bit REAL, and the arithmetic results diverge due to
        # rounding. Integer values (< 2^24) are exactly representable
        # in 32-bit REAL, so the CHECK holds exactly.
        #
        # IMPORTANT: skip conversion when the source column has
        # its OWN single-column range CHECK constraint with a
        # small upper bound (e.g., ``interest_rate <= 0.5``).
        # Converting such a column to ``integer`` would produce
        # values like 0-100 that violate the CHECK. The column
        # keeps its ``float`` generator with the CHECK-derived
        # bounds (e.g., ``min_value: 0.0, max_value: 0.5``).
        # The arithmetic equality CHECK on the derived column
        # (e.g., ``expected_interest = principal * interest_rate
        # * term_months / 12.0``) still holds because SQLite
        # uses 64-bit float (no 32-bit REAL precision issue),
        # and PostgreSQL tables use NUMERIC instead of REAL
        # for financial columns in practice.
        if src_gen_r == "float":
            # Check if source column has its own single-column
            # range CHECK with max_value < 1.0 (e.g., interest
            # rate 0.0-0.5, commission_rate 0.0-0.1). If so,
            # skip the integer conversion.
            if (float(src_params_r.get("max_value", 999))) < 1.0:
                # Small-range float column — keep as float to
                # preserve CHECK compliance. The REAL precision
                # issue only matters for large-value arithmetic
                # (e.g., balance * rate where balance > 1000);
                # small-range rates multiplied by large integers
                # still produce exact-enough results in 64-bit.
                return
            new_min = int(src_params_r.get("min_value", 0))
            new_max = int(src_params_r.get("max_value", 999))
            # Ensure min_value is at least 1 when original min_value
            # was > 0 (e.g., min_value=0.01 → int(0.01)=0, but
            # CHECK constraint requires > 0). Integer 0 would
            # violate ``col > 0.0`` CHECKs.
            orig_min_r = float(src_params_r.get("min_value", 0))
            if orig_min_r > 0 and new_min < 1:
                new_min = 1
            if new_max <= new_min:
                new_max = new_min + 100
            # Cap max to ensure products stay within 32-bit exact range
            # 2^24 = 16777216; sqrt(16777216) ≈ 4096, so cap at 4000 for safety
            new_max = min(new_max, 4000)
            src_col_r["generator"] = "integer"
            src_col_r["params"] = {"min_value": new_min, "max_value": new_max}

    def _apply_column_complex_check_null(self, tcfg: dict[str, Any], meta_c: TableMeta, c_c: dict[str, Any]) -> None:
        col_name_c = c_c.get("name", "")
        # Skip already-NULL columns
        if c_c.get("null_ratio", 0) >= 1.0:
            return
        # Skip autoincrement and FK columns
        if generator_name(c_c.get("generator")) in RELATION_GENERATORS:
            return
        if col_name_c not in meta_c.columns:
            return
        col_name_upper_c = col_name_c.upper()
        # Skip if ANY CHECK requires this column to be NOT NULL
        # (setting null_ratio=1.0 would violate those CHECKs)
        if self._requires_nonnull_check(meta_c, col_name_upper_c):
            return
        # Check for complex conditional CHECK (OR + IS NULL + cross-column)
        # that no pattern matched
        if self._has_unhandled_conditional_null_check(meta_c, col_name_c, col_name_upper_c):
            # Before forcing null_ratio=1.0, check if the pattern
            # engine (_infer_cross_column_config) can match this
            # column's CHECK. If it can, the pattern already
            # handled it (either via LLM-set derive_from or via the
            # cross-column restoration in the main loop) — don't
            # override. Only force null_ratio=1.0 when NO pattern
            # matched (the complex CHECK is truly unhandled).
            col_type_c = meta_c.column_types.get(col_name_c, "TEXT")
            fk_cols_set_c = self._collect_table_fk_column_names(meta_c)
            cross_result_c = _infer_cross_column_config(
                col_name_c,
                meta_c.constraints,
                meta_c.columns,
                col_type_c,
                fk_cols_set_c,
                column_types=meta_c.column_types,
            )
            if cross_result_c is not None and "derive_from" in cross_result_c:
                # Pattern matched — skip null_ratio override
                return
            # Skip columns that are the source of another column's
            # derive_from. Setting null_ratio=1.0 here would cascade
            # NULLs to dependent columns, and the dependent's
            # derive_from expression usually handles the CHECK
            # constraint on its own (e.g., estimated_delivery derives
            # from guaranteed_delivery via
            # ``value - timedelta(days=...)`` which inherently satisfies
            # ``estimated_delivery < guaranteed_delivery``). The
            # pattern engine returns None for the SOURCE column
            # because the CHECK is ``other < col`` (reversed), but
            # the dependent column already has the correct
            # derive_from — forcing NULL here is both unnecessary
            # and harmful (destroys the upgraded ``date`` generator
            # set by the timedelta source upgrade in Step 5.5).
            is_derive_source_c = False
            for _other_c in tcfg.get("columns", []):
                if _other_c.get("derive_from") == col_name_c:
                    is_derive_source_c = True
                    break
            if is_derive_source_c:
                return
            c_c["null_ratio"] = 1.0
            # Remove generator/params/derive_from since null_ratio=1.0
            # means all NULL
            c_c.pop("generator", None)
            c_c.pop("params", None)
            c_c.pop("derive_from", None)
            c_c.pop("expression", None)

    def _requires_nonnull_check(self, meta_c: TableMeta, col_name_upper_c: str) -> bool:
        requires_not_null_c = False
        for constraint_c in meta_c.constraints:
            if constraint_c.get("type") != "check":
                continue
            expr_c_norm = _normalize_pg_check_expr(constraint_c.get("expression", ""))
            if f"{col_name_upper_c} IS NOT NULL" in expr_c_norm.upper():
                requires_not_null_c = True
                break
        return requires_not_null_c

    def _has_unhandled_conditional_null_check(self, meta_c: TableMeta, col_name_c: str, col_name_upper_c: str) -> bool:
        has_complex_check_c = False
        for constraint_c in meta_c.constraints:
            if constraint_c.get("type") != "check":
                continue
            if not (expr_c := constraint_c.get("expression", "")):
                continue
            expr_c_norm = _normalize_pg_check_expr(expr_c)
            expr_c_upper = expr_c_norm.upper()
            if col_name_upper_c not in expr_c_upper:
                continue
            # Complex conditional: has OR with IS NULL for this column
            # AND THIS expression references other columns.
            #
            # NOTE: Previously called ``_has_cross_column_check(
            # col_name_c, meta_c.constraints)`` which checks ALL
            # constraints in the table. This caused single-column
            # range CHECKs like ``col IS NULL OR (col >= 60 AND
            # col <= 250)`` to be misclassified as complex
            # cross-column CHECKs when the table happens to have
            # OTHER cross-column CHECKs referencing this column
            # (e.g., R2 medical_records.blood_pressure_high has a
            # single-column range CHECK but the table also has
            # ``blood_pressure_low < blood_pressure_high``). This
            # led to incorrect null_ratio=1.0 being set, which then
            # got params overwritten by Safety net 7's fallback
            # (min_value=0 instead of 60). Fix: check THIS expression
            # only, not the whole table.
            tokens_c = set(re.findall(r"\b[a-z_]\w*\b", expr_c_norm.lower()))
            sql_keywords_c = {
                "and",
                "or",
                "not",
                "null",
                "is",
                "in",
                "between",
                "like",
                "case",
                "when",
                "then",
                "else",
                "end",
                "abs",
                "length",
                "date",
                "time",
                "timestamp",
                "true",
                "false",
            }
            col_refs_c = tokens_c - sql_keywords_c - {col_name_c.lower()}
            col_refs_c = {t for t in col_refs_c if not t.isdigit()}
            # Only count references to actual OTHER column names
            other_col_refs_c = col_refs_c & (set(meta_c.columns) - {col_name_c})
            if " OR " in expr_c_upper and f"{col_name_upper_c} IS NULL" in expr_c_upper and other_col_refs_c:
                has_complex_check_c = True
                break
        return has_complex_check_c

    def _collect_status_null_triggers(self, meta_sn: TableMeta) -> dict[str, dict[str, set[str]]]:
        null_triggers: dict[str, dict[str, set[str]]] = {}
        for constraint_sn in meta_sn.constraints:
            if constraint_sn.get("type") != "check":
                continue
            expr_sn = _normalize_pg_check_expr(constraint_sn.get("expression", ""))
            if not expr_sn or " OR " not in expr_sn.upper():
                continue
            # Split by OR (case-insensitive) — each clause may contain
            # ``cond_col = 'V' AND ... AND col IS NULL``
            # Use regex to split on top-level OR (not inside parens)
            clauses_sn = re.split(r"\bOR\b", expr_sn, flags=re.IGNORECASE)
            for clause_raw_sn in clauses_sn:
                clause_sn = clause_raw_sn.strip().strip("()")
                # Find cond_col = 'V' patterns
                if not (cond_matches := re.findall(r"(\w+)\s*=\s*'([^']+)'", clause_sn)):
                    continue
                # Find col IS NULL patterns
                if not (null_matches := re.findall(r"(\w+)\s+IS\s+NULL", clause_sn, re.IGNORECASE)):
                    continue
                for cond_col_sn, cond_val_sn in cond_matches:
                    for null_col_sn in null_matches:
                        if null_col_sn.upper() == cond_col_sn.upper():
                            continue
                        null_triggers.setdefault(null_col_sn, {}).setdefault(cond_col_sn, set()).add(cond_val_sn)
        return null_triggers

    def _apply_column_status_null(
        self,
        meta_sn: TableMeta,
        col_map_sn: dict[str, dict[str, Any]],
        columns_sn: list[dict[str, Any]],
        col_sn: str,
        triggers_sn: dict[str, set[str]],
    ) -> None:
        if (c_sn := col_map_sn.get(col_sn)) is None:
            return
        # Skip if column already has null_ratio=1.0
        if c_sn.get("null_ratio", 0) >= 1.0:
            return
        # Skip autoincrement and FK columns
        if generator_name(c_sn.get("generator")) in RELATION_GENERATORS:
            return
        # Only one cond_col supported (multiple cond_cols on same col
        # would require nested ternary — rare and complex)
        if len(triggers_sn) != 1:
            return
        cond_col_sn = next(iter(triggers_sn))
        null_vals_sn = triggers_sn[cond_col_sn]
        # Build the tuple of NULL-triggering values
        vals_tuple_str = ", ".join(f"'{v}'" for v in sorted(null_vals_sn))
        vals_in_expr = f"row.get('{cond_col_sn}') in ({vals_tuple_str})"
        # Check if cond_col exists in the table
        if cond_col_sn not in col_map_sn:
            return
        existing_derive_sn = c_sn.get("derive_from", "")
        existing_expr_sn = str(c_sn.get("expression", ""))
        if existing_derive_sn:
            # Case 1: col already has derive_from — wrap existing expr
            # Only wrap if not already wrapped (idempotent)
            if vals_in_expr not in existing_expr_sn:
                new_expr_sn = f"None if {vals_in_expr} else ({existing_expr_sn})"
                c_sn["expression"] = new_expr_sn
        else:
            # Case 2: col has no derive_from — find anchor datetime column
            if (anchor_col_sn := self._find_status_datetime_anchor(columns_sn, meta_sn, col_sn, cond_col_sn)) is None:
                return
            # Set derive_from: cond_col, expression returns None for
            # trigger values, else anchor + random timedelta
            c_sn["derive_from"] = cond_col_sn
            c_sn["generator"] = None
            c_sn.pop("params", None)
            c_sn.pop("null_ratio", None)
            c_sn["expression"] = (
                f"None if value in ({vals_tuple_str}) else row['{anchor_col_sn}'] + timedelta(days=random_int(0, 30))"
            )

    def _enforce_column_notnull_check(self, context: _NotNullRuleContext, c_sn7: dict[str, Any]) -> None:
        meta_sn7 = context.meta_sn7
        self_ref_fk_cols_sn7 = context.self_ref_fk_cols_sn7
        fk_cols_set_sn7 = context.fk_cols_set_sn7
        if c_sn7.get("null_ratio", 0) < 1.0:
            return
        if (col_name_sn7 := c_sn7.get("name", "")) not in meta_sn7.columns:
            return
        col_name_upper_sn7 = col_name_sn7.upper()
        is_self_ref_fk_sn7 = col_name_sn7 in self_ref_fk_cols_sn7
        # Check if any CHECK constraint requires this column to be
        # NOT NULL (contains ``IS NOT NULL`` for this column).
        requires_not_null_sn7 = self._requires_nonnull_check(meta_sn7, col_name_upper_sn7)
        # Check if any non-null_ratio column derives from this column
        # (case b). If a dependent column has no null_ratio and
        # derives_from this null_ratio=1.0 column, the dependent will
        # likely produce NULL values when the source is NULL, causing
        # NOT NULL constraint failures if the dependent is NOT NULL.
        has_non_null_dependent_sn7 = self._has_nonnull_dependent(context, col_name_sn7)
        if not requires_not_null_sn7 and not has_non_null_dependent_sn7:
            return
        # Case (c): self-ref FK with IS NOT NULL CHECK — keep
        # null_ratio, restrict the conditional column's choices to
        # the NULL-allowing value. This avoids the chicken-and-egg
        # problem of self-ref FK during initial bulk fill.
        if is_self_ref_fk_sn7 and requires_not_null_sn7:
            # Find Pattern 30b matching: ``col1 = 'VALUE' OR col IS NOT NULL``
            # to identify the NULL-allowing value for the conditional column.
            self._restrict_self_reference_condition(context, col_name_upper_sn7)
            return
        # Cases (a) and (b): clear null_ratio and set a non-NULL generator
        c_sn7.pop("null_ratio", None)
        col_type_sn7 = meta_sn7.column_types.get(col_name_sn7, "TEXT")
        # Try to apply a cross-column pattern (Pattern 30b, 30b NOT IN, etc.)
        cross_result_sn7 = _infer_cross_column_config(
            col_name_sn7,
            meta_sn7.constraints,
            meta_sn7.columns,
            col_type_sn7,
            fk_cols_set_sn7,
            self_ref_fk_cols=self_ref_fk_cols_sn7,
            column_types=meta_sn7.column_types,
        )
        # Ignore results that re-introduce null_ratio=1.0 — Safety
        # net 7's purpose is to CLEAR null_ratio so the column
        # produces non-NULL values. Some patterns (e.g., Pattern 4:
        # ``col IS NULL OR col = expr``) return null_ratio=1.0 as a
        # safe fallback, but that defeats Safety net 7's goal. Only
        # accept results that have ``derive_from`` (useful) and do
        # NOT have ``null_ratio: 1.0``.
        if cross_result_sn7 is not None and cross_result_sn7.get("null_ratio", 0) >= 1.0:
            cross_result_sn7 = None
        if cross_result_sn7 is not None:
            # Pattern matched — use the derive_from config.
            c_sn7.pop("generator", None)
            c_sn7.pop("params", None)
            c_sn7.update(cross_result_sn7)
        else:
            self._restore_nonnull_fallback(context, c_sn7, col_name_sn7, col_name_upper_sn7, col_type_sn7)

    def _has_nonnull_dependent(self, context: _NotNullRuleContext, col_name_sn7: str) -> bool:
        tcfg_sn7 = context.tcfg_sn7
        derive_dependents_sn7 = context.derive_dependents_sn7
        has_non_null_dependent_sn7 = False
        for dep_col_name in derive_dependents_sn7.get(col_name_sn7, []):
            for dep_c in tcfg_sn7.get("columns", []):
                if dep_c.get("name") == dep_col_name and dep_c.get("null_ratio", 0) < 1.0:
                    has_non_null_dependent_sn7 = True
                    break
            if has_non_null_dependent_sn7:
                break
        return has_non_null_dependent_sn7

    def _restrict_self_reference_condition(self, context: _NotNullRuleContext, col_name_upper_sn7: str) -> None:
        meta_sn7 = context.meta_sn7
        tcfg_sn7 = context.tcfg_sn7
        for constraint_sn7 in meta_sn7.constraints:
            if constraint_sn7.get("type") != "check":
                continue
            expr_sn7_norm = _normalize_pg_check_expr(constraint_sn7.get("expression", ""))
            m_p30b_sn7 = re.match(
                rf"^\s*(\w+)\s*=\s*'([^']+)'\s+OR\s+{col_name_upper_sn7}\s+IS\s+NOT\s+NULL\s*$",
                expr_sn7_norm,
                re.IGNORECASE,
            )
            if m_p30b_sn7:
                cond_col_sn7 = m_p30b_sn7.group(1)
                null_val_sn7 = m_p30b_sn7.group(2)
                # Restrict the conditional column's choices to
                # just [null_val] so the CHECK is always satisfied
                # via the ``col1 = 'VALUE'`` branch.
                for c_cond in tcfg_sn7.get("columns", []):
                    if c_cond.get("name") == cond_col_sn7:
                        c_cond["generator"] = "choice"
                        c_cond["params"] = {"choices": [null_val_sn7]}
                        c_cond.pop("derive_from", None)
                        c_cond.pop("expression", None)
                        break
                break  # Only need to match one Pattern 30b

    def _collect_table_fk_column_names(self, meta_c: TableMeta) -> set[str]:
        fk_cols_set_c: set[str] = set()
        for fk_c in meta_c.foreign_keys:
            for fc_c in fk_c.get("columns", []):
                fk_cols_set_c.add(fc_c)
        return fk_cols_set_c

    def _find_status_datetime_anchor(
        self, columns_sn: list[dict[str, Any]], meta_sn: TableMeta, col_sn: str, cond_col_sn: str
    ) -> str | None:
        anchor_col_sn = None
        for ac_sn in columns_sn:
            if (ac_name_sn := ac_sn.get("name", "")) in (col_sn, cond_col_sn):
                continue
            ac_type_sn = meta_sn.column_types.get(ac_name_sn, "")
            ac_gen_sn = ac_sn.get("generator")
            # Anchor must be datetime/date type, non-NULL, no derive_from
            if (
                ac_type_sn.upper()
                in {
                    "TIMESTAMP",
                    "TIMESTAMPTZ",
                    "DATETIME",
                    "DATE",
                    "TIMESTAMP WITHOUT TIME ZONE",
                    "TIMESTAMP WITH TIME ZONE",
                }
                and generator_name(ac_gen_sn) in DATE_GENERATORS
                and ac_sn.get("null_ratio", 0) < 1.0
            ):
                anchor_col_sn = ac_name_sn
                break
        return anchor_col_sn

    def _restore_nonnull_fallback(
        self,
        context: _NotNullRuleContext,
        c_sn7: dict[str, Any],
        col_name_sn7: str,
        col_name_upper_sn7: str,
        col_type_sn7: str,
    ) -> None:
        fk_cols_set_sn7 = context.fk_cols_set_sn7
        # No usable cross-column pattern matched. Before
        # falling back to a default non-NULL value, check if
        # there is a Pattern 30b NOT IN constraint
        # (``col1 NOT IN (...) OR col IS NOT NULL``). If so,
        # the column CAN be NULL — we just need to ensure
        # ``col1`` never takes a value in the NOT IN set.
        # This is necessary when the column also has complex
        # multi-clause CHECKs that require specific computed
        # values (which a random default cannot satisfy). By
        # keeping null_ratio=1.0 and restricting conditional
        # columns' choices, both the NOT NULL CHECK and the
        # complex CHECK are satisfied (each branch allows
        # ``col IS NULL``).
        # e.g., R7 claims.approved_amount:
        #   CHECK (status NOT IN ('approved','settled')
        #         OR approved_amount IS NOT NULL)
        #   CHECK ((claim_type IN ('medical','accident')
        #          AND approved_amount IS NULL OR ...)
        #         OR (claim_type IN ('property_damage','theft')
        #          AND approved_amount IS NULL OR ...))
        # Solution: keep approved_amount = NULL, restrict
        # status to exclude {'approved','settled'}, restrict
        # claim_type to {'medical','accident',
        # 'property_damage','theft'} (exclude 'death').
        if not self._restore_notin_null_escape(context, c_sn7, col_name_upper_sn7):
            # No Pattern 30b NOT IN matched — set a safe
            # non-NULL default. But PRESERVE any existing
            # generator+params that were set by earlier steps
            # (Step 5.5 Case 5, _build_subgraph_config, etc.)
            # to avoid overwriting correct CHECK-inferred
            # ranges with generic defaults (e.g., overwriting
            # ``min_value=60`` with ``min_value=0``).
            existing_gen_sn7 = c_sn7.get("generator")
            existing_params_sn7 = c_sn7.get("params")
            if existing_gen_sn7 and existing_params_sn7 is not None:
                # Column already has a valid generator+params —
                # keep them, just ensure null_ratio is cleared.
                pass
            elif col_name_sn7 in fk_cols_set_sn7:
                c_sn7["generator"] = "foreign_key_or_integer"
                c_sn7["params"] = {}
            elif "INT" in col_type_sn7.upper():
                c_sn7["generator"] = "integer"
                c_sn7["params"] = {"min_value": 0}
            elif any(k in col_type_sn7.upper() for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")):
                c_sn7["generator"] = "float"
                # Use 0.01 (not 0.0) to satisfy ``> 0.0`` CHECKs
                c_sn7["params"] = {"min_value": 0.01}
            elif any(k in col_type_sn7.upper() for k in ("DATETIME", "TIMESTAMP")):
                # DATETIME/TIMESTAMP must be checked before
                # DATE because "DATE" is a substring of
                # "DATETIME". Without this branch, DATE-type
                # columns fall through to ``generator: string``
                # which is semantically wrong (e.g.,
                # guaranteed_delivery DATE → string "abc").
                c_sn7["generator"] = "datetime"
                c_sn7["params"] = {}
            elif "DATE" in col_type_sn7.upper():
                c_sn7["generator"] = "date"
                c_sn7["params"] = {}
            else:
                c_sn7["generator"] = "string"
                c_sn7["params"] = {"min_length": 1, "max_length": 50}

    def _restore_notin_null_escape(
        self, context: _NotNullRuleContext, c_sn7: dict[str, Any], col_name_upper_sn7: str
    ) -> bool:
        meta_sn7 = context.meta_sn7
        tcfg_sn7 = context.tcfg_sn7
        p30b_notin_matched_sn7 = False
        for constraint_sn7 in meta_sn7.constraints:
            if constraint_sn7.get("type") != "check":
                continue
            expr_sn7_norm = _normalize_pg_check_expr(constraint_sn7.get("expression", ""))
            m_p30b_notin_sn7 = re.match(
                rf"^\s*(\w+)\s+NOT\s+IN\s*\(([^)]+)\)\s+OR\s+{col_name_upper_sn7}\s+IS\s+NOT\s+NULL\s*$",
                expr_sn7_norm,
                re.IGNORECASE,
            )
            if not m_p30b_notin_sn7:
                continue
            cond_col_sn7 = m_p30b_notin_sn7.group(1)
            values_str_sn7 = m_p30b_notin_sn7.group(2)
            not_in_values_sn7 = re.findall(r"'([^']*)'", values_str_sn7)
            if cond_col_sn7 not in meta_sn7.columns:
                continue
            # Restore null_ratio=1.0 for the target column
            c_sn7["null_ratio"] = 1.0
            c_sn7.pop("generator", None)
            c_sn7.pop("params", None)
            c_sn7.pop("derive_from", None)
            c_sn7.pop("expression", None)
            self._exclude_null_escape_values(tcfg_sn7, cond_col_sn7, not_in_values_sn7)
            self._restrict_conditional_null_values(tcfg_sn7, meta_sn7, col_name_upper_sn7)
            p30b_notin_matched_sn7 = True
            break
        return p30b_notin_matched_sn7

    def _exclude_null_escape_values(
        self, tcfg_sn7: dict[str, Any], cond_col_sn7: str, not_in_values_sn7: list[str]
    ) -> None:
        # Step 1: restrict the Pattern 30b NOT IN
        # conditional column's choices to EXCLUDE the
        # NOT IN set values.
        for c_cond in tcfg_sn7.get("columns", []):
            if c_cond.get("name") != cond_col_sn7:
                continue
            cur_choices = c_cond.get("params", {}).get("choices")
            if isinstance(cur_choices, list) and (filtered := [v for v in cur_choices if v not in not_in_values_sn7]):
                c_cond["params"]["choices"] = filtered
            break

    def _restrict_conditional_null_values(
        self, tcfg_sn7: dict[str, Any], meta_sn7: TableMeta, col_name_upper_sn7: str
    ) -> None:
        # Step 2: scan ALL CHECK constraints for
        # conditional NULL patterns:
        # ``col_X IN (...) AND {col} IS NULL``. The
        # column ``col_X`` must be in the union of all
        # such IN sets for ``{col} = NULL`` to satisfy
        # the CHECK. If ``col_X`` has a choice
        # generator, restrict its choices to that union.
        # e.g., the complex multi-clause CHECK requires
        # claim_type IN ('medical','accident',
        # 'property_damage','theft') for
        # approved_amount = NULL (excluding 'death').
        allowed_values_per_col_sn7: dict[str, set[str]] = {}
        for constraint_cn in meta_sn7.constraints:
            if constraint_cn.get("type") != "check":
                continue
            expr_cn_norm = _normalize_pg_check_expr(constraint_cn.get("expression", ""))
            for m_in_null in re.finditer(
                rf"(\w+)\s+IN\s*\(([^)]+)\)\s+AND\s+{col_name_upper_sn7}\s+IS\s+NULL",
                expr_cn_norm,
                re.IGNORECASE,
            ):
                cond_col_cn = m_in_null.group(1)
                values_str_cn = m_in_null.group(2)
                if not (values_cn := re.findall(r"'([^']*)'", values_str_cn)):
                    values_cn = [v.strip() for v in values_str_cn.split(",")]
                allowed_values_per_col_sn7.setdefault(cond_col_cn, set()).update(values_cn)
        for cond_col_cn, allowed_cn in allowed_values_per_col_sn7.items():
            for c_cond in tcfg_sn7.get("columns", []):
                if c_cond.get("name") != cond_col_cn:
                    continue
                cur_choices = c_cond.get("params", {}).get("choices")
                if isinstance(cur_choices, list) and (filtered := [v for v in cur_choices if v in allowed_cn]):
                    c_cond["params"]["choices"] = filtered
                break

    def _upgrade_restored_timedelta_source(
        self, tcfg: dict[str, Any], meta: TableMeta | None, source_name: str
    ) -> None:
        for source in tcfg.get("columns", []):
            if source.get("name") != source_name:
                continue
            source_generator = source.get("generator")
            # A derived source must retain its existing dependency.
            if needs_typed_source(source_generator) and not source.get("derive_from"):
                source_type = (meta.column_types.get(source_name, "") if meta else "") or ""
                source["generator"] = "date" if _is_date_only_type(source_type) else "datetime"
                source.pop("params", None)
                source["params"] = {}
            break

    def _build_fk_graph(self, snapshot: SchemaSnapshot) -> dict[str, list[str]]:
        """Build FK adjacency list from snapshot.

        Each ``TableMeta.foreign_keys`` entry has keys ``columns``,
        ``ref_table``, ``ref_columns``. Edge direction: source table →
        referenced (parent) table.
        """
        graph: dict[str, list[str]] = {t: [] for t in snapshot.tables}
        for table_name, meta in snapshot.tables.items():
            for fk in meta.foreign_keys:
                if ref_table := fk.get("ref_table"):
                    graph.setdefault(table_name, []).append(ref_table)
                    graph.setdefault(ref_table, [])
        return graph

    def _build_subgraph_config(
        self,
        tables: list[str],
        snapshot: SchemaSnapshot,
    ) -> dict[str, Any]:
        """Build initial config for a subgraph (smart placeholders).

        Parses CHECK constraints to infer ``choice`` generators for enum
        columns and ``min_value``/``max_value`` params for range constraints.
        Detects UNIQUE columns and uses ``template`` generators to guarantee
        uniqueness (avoids batch-level UNIQUE violations from random string
        collisions). For unconstrained columns, delegates to the Core
        ``ColumnMapper`` (9-level strategy chain: 76 exact match rules +
        29 pattern rules) for semantic column name matching — e.g.,
        ``email``→email generator, ``avatar_url``→url generator,
        ``title``→sentence generator. FK constraints are still deferred
        to Layer 3/4.
        """
        sg_config: dict[str, Any] = {"tables": []}
        for table_name in tables:
            if (meta := snapshot.tables.get(table_name)) is None:
                continue
            sg_config["tables"].append(_build_initial_table_config(table_name, meta, snapshot))
        return sg_config

    def _append_default_columns(
        self,
        config: dict[str, Any],
        tables: list[str],
        snapshot: SchemaSnapshot,
    ) -> None:
        """Fallback: build smart configs for tables skipped due to time budget.

        Previously appended ``integer`` for ALL columns, which caused
        ``TypeError`` when a ``derive_from`` expression used ``timedelta``
        arithmetic on a datetime column that got the integer default.
        Now delegates to ``_build_subgraph_config`` so CHECK constraints,
        column types, and ColumnMapper semantic matching are all applied —
        producing a fillable config even without an LLM round-trip.
        """
        sg_config = self._build_subgraph_config(tables, snapshot)
        for tcfg in sg_config.get("tables", []):
            config["tables"].append(tcfg)

    def _validate(
        self,
        config: dict[str, Any],
        snapshot: SchemaSnapshot,
    ) -> list[Any]:
        """Call validator and normalize return value to a list of violations.

        Duck-typed: supports both list returns (mocks) and
        ``ValidationResult`` returns (real FastValidator).
        """
        try:
            result = self._validator.validate(config, snapshot)
        except TypeError:
            # Validator may not accept snapshot kwarg (e.g., plain mock)
            result = self._validator.validate(config)
        # Normalize: ValidationResult has .violations; list is used directly
        if hasattr(result, "violations"):
            return list(result.violations)
        return list(result or [])

    def _heal_subgraph(
        self,
        sg_config: dict[str, Any],
        sg_tables: list[str],
        violations: list[Any],
        snapshot: SchemaSnapshot,
        schema_hash: str,
        budget: TimeBudgetController,
    ) -> dict[str, Any]:
        """Run Layer 3 + Layer 4 healing for a single subgraph."""
        # Layer 3: local rule-based repair (cheap, deterministic). Runs
        # before the expensive LLM healer so that simple violations (e.g.,
        # generator param typos, type mismatches) can be fixed without an
        # LLM round-trip. If Layer 3 fixes everything, skip Layer 4.
        try:
            from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
            from sqlseed_ai.contracts.matrix import ContractResolver
            from sqlseed_ai.repair.pipeline import RepairPipeline

            resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
            repair_pipe = RepairPipeline(resolver, db_path=self._db_path, url=self._url)
            # RepairPipeline.run() returns (config, RepairResult). The
            # config may be mutated in-place by RepairExecutor.
            sg_config, _ = repair_pipe.run(sg_config, snapshot)
            # Re-validate to check if Layer 3 resolved all violations.
            if not (remaining := self._validate(sg_config, snapshot)):
                if self._verbose:
                    _debug("[ai-analyze]     Layer 3 (repair) resolved all violations — skipping LLM")
                return sg_config  # Layer 3 fixed everything
            # Carry over remaining violations for Layer 4.
            if self._verbose:
                _debug(f"[ai-analyze]     Layer 3 (repair) left {len(remaining)} violations — proceeding to LLM")
            violations = remaining
        except ImportError as e:
            logger.warning(
                "Layer 3 repair unavailable, proceeding to Layer 4",
                error=str(e),
            )

        # Layer 4: 4-level LLM healing (subgraph → column → compact → degrade)
        from sqlseed_ai.healer.models import SubgraphTask

        if self._verbose:
            _debug(f"[ai-analyze]     Layer 4: calling HealOrchestrator (max_rounds={self._max_retries}) ...")
        task = SubgraphTask(
            task_id=f"sg_{sg_tables[0] if sg_tables else 'empty'}",
            tables=sg_tables,
            is_scc=len(sg_tables) > 1,
        )
        # HealOrchestrator.heal returns HealResult with .config
        result = self._heal_orchestrator.heal(task, violations, sg_config)
        if self._verbose:
            level = getattr(result, "level_used", 0)
            success = getattr(result, "success", False)
            degraded = getattr(result, "degraded_columns", [])
            _debug(f"[ai-analyze]     Layer 4 done: level={level} success={success} degraded={len(degraded)}")
        config: dict[str, Any] = result.config
        return config


@dataclass(frozen=True)
class _ForeignKeyColumns:
    """Column sets needed to preserve FK-specific initial configuration rules."""

    all: set[str]
    self_referencing: set[str]
    circular: set[str]


def _has_returning_foreign_key(table_name: str, ref_table_name: str | None, snapshot: SchemaSnapshot) -> bool:
    """Check whether the referenced table points back to the current table."""
    if not ref_table_name or ref_table_name not in snapshot.tables:
        return False
    ref_meta = snapshot.tables[ref_table_name]
    return any(ref_fk.get("ref_table") == table_name for ref_fk in ref_meta.foreign_keys)


def _collect_initial_foreign_keys(table_name: str, meta: TableMeta, snapshot: SchemaSnapshot) -> _ForeignKeyColumns:
    """Classify ordinary, self-referencing and two-table circular FK columns."""
    columns = _ForeignKeyColumns(set(), set(), set())
    for foreign_key in meta.foreign_keys:
        names = foreign_key.get("columns", [])
        columns.all.update(names)
        if foreign_key.get("ref_table") == table_name:
            columns.self_referencing.update(names)
        elif _has_returning_foreign_key(table_name, foreign_key.get("ref_table"), snapshot):
            columns.circular.update(names)
    return columns


def _build_initial_table_config(table_name: str, meta: TableMeta, snapshot: SchemaSnapshot) -> dict[str, Any]:
    """Build columns in schema order with the table's UNIQUE and FK context."""
    unique_columns = _get_unique_columns(meta.constraints)
    foreign_keys = _collect_initial_foreign_keys(table_name, meta, snapshot)
    columns = [_build_initial_column_config(name, meta, unique_columns, foreign_keys) for name in meta.columns]
    return {"name": table_name, "columns": columns}


def _build_initial_column_config(
    col_name: str,
    meta: TableMeta,
    unique_columns: set[str],
    foreign_keys: _ForeignKeyColumns,
) -> dict[str, Any]:
    """Select FK, cross-column CHECK, single-column CHECK, UNIQUE, then mapping."""
    col_type = meta.column_types.get(col_name, "TEXT")
    # Step 0 / Step 0c: self-referencing and two-table circular FKs must
    # precede all other inference. Their parent's pool is empty at initial
    # fill time, so foreign_key_or_integer would generate invalid keys.
    # Both cases retain null_ratio=1.0 rather than an unsafe literal 0.
    if col_name in foreign_keys.self_referencing or col_name in foreign_keys.circular:
        return {
            "name": col_name,
            "generator": "foreign_key_or_integer",
            "params": {},
            "null_ratio": 1.0,
        }
    # Step 1: cross-column relationships take priority over independent
    # ranges; keep FK sets and full column types available to Pattern 30
    # and date/time inference.
    cross_config = _infer_cross_column_config(
        col_name,
        meta.constraints,
        meta.columns,
        col_type,
        foreign_keys.all,
        foreign_keys.self_referencing,
        column_types=meta.column_types,
    )
    if cross_config is not None:
        return {"name": col_name, **cross_config}
    # Step 2: single-column CHECKs precede generic UNIQUE/name inference.
    if (inferred := _infer_from_check_constraints(col_name, meta.constraints, meta.columns)) is not None:
        return _adapt_initial_check_column(col_name, col_type, col_name in unique_columns, inferred)
    # Step 3: preserve the UNIQUE generator fallback after CHECK inference.
    if col_name in unique_columns and (unique_config := _infer_unique_column_config(col_name, col_type)) is not None:
        return {"name": col_name, **unique_config}
    return _map_initial_column(col_name, col_type)


def _has_exact_check_length(params: dict[str, Any]) -> bool:
    """Return whether both string length bounds specify the same length."""
    return "min_length" in params and "max_length" in params and params["min_length"] == params["max_length"]


def _adapt_initial_check_column(
    col_name: str,
    col_type: str,
    is_unique: bool,
    inferred: tuple[str, dict[str, Any]],
) -> dict[str, Any]:
    """Preserve REAL promotion and UNIQUE/phone CHECK conflict resolution."""
    gen, params = inferred
    # Integer literals in a REAL/FLOAT CHECK still require the float generator.
    if gen == "integer" and any(k in col_type.upper() for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")):
        gen = "float"
    # UNIQUE + exact LENGTH must use pattern: UniqueAdjuster may widen
    # string max_length. This rule intentionally precedes phone semantics.
    if gen == "string" and is_unique and _has_exact_check_length(params):
        n = params["min_length"]
        return {"name": col_name, "generator": "pattern", "params": {"regex": f"[A-Za-z0-9]{{{n}}}"}}
    # Phone + exact LENGTH uses digits to satisfy both shape and semantics,
    # avoiding string/phone repair oscillation that loses the length CHECK.
    if gen == "string" and _is_phone_like(col_name) and _has_exact_check_length(params):
        n = params["min_length"]
        return {"name": col_name, "generator": "pattern", "params": {"regex": f"[0-9]{{{n}}}"}}
    # Preserve the existing non-exact minimum-length phone rule, including
    # its handling of a different max_length when both bounds are present.
    if (
        gen == "string"
        and _is_phone_like(col_name)
        and "min_length" in params
        and ("max_length" not in params or params["min_length"] != params["max_length"])
    ):
        return {"name": col_name, "generator": "phone", "params": {}}
    return {"name": col_name, "generator": gen, "params": params}


def _map_initial_column(col_name: str, col_type: str) -> dict[str, Any]:
    """Apply semantic mapping and the existing type/date/null fallbacks."""
    # Step 4: Delegate to Core ColumnMapper for semantic name
    # matching. The Core ColumnMapper has 76 exact match rules
    # (L3) + 29 pattern rules (L5) that map column names to
    # semantic generators: email→email, username→username,
    # avatar_url→url, title→sentence, description→sentence,
    # content→text, bio→text, phone→phone, name→name, etc.
    #
    # This replaces the previous dumb type-based fallback
    # (_placeholder_generator) which returned "string" for ALL
    # TEXT columns regardless of name — producing random
    # gibberish for email, url, username, and other
    # semantically-named columns. The LLM was never consulted
    # for these columns because 11/12 tables had 0 violations
    # and were "accepted as-is" (no LLM call).
    #
    # ColumnInfo is constructed with safe defaults
    # (is_primary_key=False, is_autoincrement=False) because:
    #   1. PK columns are typically handled by Step 2/3 (CHECK/
    #      UNIQUE constraints) and rarely reach Step 4.
    #   2. Setting is_autoincrement=False ensures the mapper's
    #      L1 skip logic does NOT skip any column — we want a
    #      generator for every column that reaches Step 4.
    col_info = ColumnInfo(
        name=col_name,
        type=col_type,
        nullable=True,
        default=None,
        is_primary_key=False,
        is_autoincrement=False,
    )
    # force_type_infer=True so that nullable columns (which is
    # every column here, since nullable=True is hardcoded above)
    # fall through to L9 type-faithful fallback instead of
    # returning "skip" at L8. This is critical for PostgreSQL-
    # specific types (UUID, JSONB, INET, CIDR, MACADDR, INTERVAL,
    # TSVECTOR, TSTZRANGE, TEXT[], INTEGER[]) which have
    # specialized generators in TYPE_FALLBACK_RULES — without
    # this, L8 would return "skip" and _placeholder_generator
    # would fall back to "string" for all of them, producing
    # invalid values that cause DataError at fill time.
    spec = _get_column_mapper().map_column(col_info, force_type_infer=True)
    gen_name = spec.generator_name
    gen_params = dict(spec.params)
    # Handle "skip" (returned for PK autoincrement columns) by
    # falling back to type-based placeholder.
    if gen_name == "skip":
        gen_name = _placeholder_generator(col_type)
        gen_params = {}
    # Additional date-column fallback: if the mapper still
    # returns "string" for a date-like column name (e.g., a
    # name not covered by the mapper's pattern rules), upgrade
    # to "datetime" so date-comparison CHECKs work correctly.
    if gen_name == "string" and _is_date_column(col_name):
        gen_name = "datetime"
    col_entry: dict[str, Any] = {
        "name": col_name,
        "generator": gen_name,
        "params": gen_params,
    }
    # Preserve null_ratio if the mapper set a non-default value
    # (e.g., for nullable columns with no default).
    if spec.null_ratio > 0:
        col_entry["null_ratio"] = spec.null_ratio
    return col_entry


# Sort constraints so conditional CHECKs (containing `` OR ``) are
# evaluated BEFORE pure range/arithmetic CHECKs (containing only
# `` AND ``). Conditional constraints are more restrictive — e.g.,
# ``status != 'paid_off' OR remaining = 0.0`` forces remaining=0
# for a specific status, while ``remaining >= 0 AND remaining <=
# principal`` only sets a range. If the range is matched first, the
# conditional is never reached, causing CHECK failures at fill time.
# By checking conditional first, the more restrictive pattern wins.
#
# Secondary sort: within conditional (OR) constraints, patterns with
# ``IN (...)`` (Pattern 35: ``col1 IN (...) OR col2 IS NULL``) get
# priority over ``IS NULL OR`` patterns (Pattern 1: ``col IS NULL OR
# col > other``). This ensures Pattern 35 is matched before Pattern 1,
# so ``completed_at`` gets ``null_ratio=1.0`` (always NULL) instead of
# ``derive_from: created_at`` (always non-NULL). Without this, Pattern 1
# would make completed_at always non-NULL, violating the Pattern 35
# CHECK (``status IN ('completed') OR completed_at IS NULL``).


# Keep the existing CHECK call signatures available at this module boundary.
def _get_exact_length_check(col_name: str, constraints: list[dict[str, Any]]) -> int | None:
    return _check_inference._get_exact_length_check(col_name, constraints)


def _get_unique_columns(constraints: list[dict[str, Any]]) -> set[str]:
    return _check_inference._get_unique_columns(constraints)


def _has_cross_column_check(col_name: str, constraints: list[dict[str, Any]]) -> bool:
    return _check_inference._has_cross_column_check(col_name, constraints)


def _has_like_constraint(col_name: str, constraints: list[dict[str, Any]]) -> bool:
    return _check_inference._has_like_constraint(col_name, constraints)


def _infer_from_check_constraints(
    col_name: str, constraints: list[dict[str, Any]], all_columns: list[str] | None = None
) -> tuple[str, dict[str, Any]] | None:
    return _check_inference._infer_from_check_constraints(col_name, constraints, all_columns)


def _infer_unique_column_config(col_name: str, col_type: str) -> dict[str, Any] | None:
    return _check_inference._infer_unique_column_config(col_name, col_type)


def _is_date_column(col_name: str) -> bool:
    return _check_inference._is_date_column(col_name)


def _is_date_only_type(col_type: str) -> bool:
    return _check_inference._is_date_only_type(col_type)


def _is_datetime_type(col_type: str) -> bool:
    return _check_inference._is_datetime_type(col_type)


def _like_to_regex(like_pattern: str) -> str:
    return _check_inference._like_to_regex(like_pattern)


def _normalize_constraints(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _check_inference._normalize_constraints(constraints)


def _normalize_pg_check_expr(expr: str) -> str:
    return _check_inference._normalize_pg_check_expr(expr)


def _parse_single_column_check(col_name: str, expr: str) -> tuple[str, dict[str, Any]] | None:
    return _check_inference._parse_single_column_check(col_name, expr)


def _placeholder_generator(col_type: str) -> str:
    return _check_inference._placeholder_generator(col_type)


def _range_expr_for_op(op: str, x: float) -> str:
    return _check_inference._range_expr_for_op(op, x)


def _infer_cross_column_config(
    col_name: str,
    constraints: list[dict[str, Any]],
    all_columns: list[str],
    col_type: str,
    fk_columns: set[str] | None = None,
    self_ref_fk_cols: set[str] | None = None,
    column_types: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    return _cross_column_checks._infer_cross_column_config(
        col_name, constraints, all_columns, col_type, fk_columns, self_ref_fk_cols, column_types
    )


@dataclass(frozen=True)
class _RunPhaseContext:
    config: dict[str, Any]
    snapshot: SchemaSnapshot
    original_hash: str
    budget: TimeBudgetController
    subgraphs: list[list[str]]
    initial_tables: dict[str, dict[str, Any]] | None
    input_violations: set[tuple[str, str]]


@dataclass(frozen=True)
class _ColumnRuleContext:
    config: dict[str, Any]
    snapshot: SchemaSnapshot
    tcfg: dict[str, Any]
    table_name: str
    req_digits: int
    meta: TableMeta | None
    timedelta_sources: dict[str, str]
    state_machine_dates: dict[str, tuple[str, set[str]]]
    phone_length_constraints: dict[str, int]
    _strip_invalid_params: Callable[[dict[str, Any], str], dict[str, Any]]


@dataclass(frozen=True)
class _NotNullRuleContext:
    tcfg_sn7: dict[str, Any]
    meta_sn7: TableMeta
    self_ref_fk_cols_sn7: set[str]
    fk_cols_set_sn7: set[str]
    derive_dependents_sn7: dict[str, list[str]]
