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
from functools import lru_cache
from typing import Any

import yaml
from sqlseed_ai.auto_heal.time_budget import TimeBudgetController
from sqlseed_ai.healer.post_repair import BrokenEdgeAligner
from sqlseed_ai.healer.subgraph import SubgraphSplitter
from sqlseed_ai.repair.strategies import _is_phone_like
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import ColumnMapper
from sqlseed.database._protocol import ColumnInfo

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_column_mapper() -> ColumnMapper:
    """Return a shared ColumnMapper instance (cached).

    ColumnMapper is stateless after __init__ (custom rules are registered
    at startup), so a single shared instance is safe for concurrent reads.
    ``lru_cache(maxsize=1)`` avoids re-creating the mapper (and re-compiling
    29 regex patterns) on every column lookup.
    """
    return ColumnMapper()


def _debug(msg: str) -> None:
    """Print a progress message to stderr for user-visible debugging.

    Used by ``ai-analyze`` to show what the auto-heal pipeline is doing in
    real time (snapshot, subgraph splitting, per-table validate/repair/heal,
    LLM calls, degraded columns). Output goes to stderr so it does not
    pollute the YAML written to stdout.
    """
    print(msg, file=sys.stderr, flush=True)


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
    ) -> str:
        """Execute the full pipeline and return the final YAML config string."""
        # Step 1: snapshot (Defense 8)
        if self._verbose:
            _debug("[ai-analyze] Step 1: capturing schema snapshot ...")
        snapshot = SchemaSnapshot(db_path=self._db_path, url=self._url)
        original_hash = snapshot.schema_hash
        if self._verbose:
            _debug(f"[ai-analyze]   schema_hash={original_hash[:12]}... tables={list(snapshot.tables.keys())}")

        # Step 2: subgraph splitting (Defenses 2 + 6)
        if self._verbose:
            _debug("[ai-analyze] Step 2: splitting FK graph into subgraphs ...")
        splitter = SubgraphSplitter(max_scc_size=self._max_scc_size)
        fk_graph = self._build_fk_graph(snapshot)
        subgraphs, broken_edges = splitter.split(fk_graph)
        if broken_edges_inject:
            broken_edges.extend(broken_edges_inject)
        if self._verbose:
            _debug(f"[ai-analyze]   subgraphs={subgraphs} broken_edges={broken_edges if broken_edges else 'none'}")

        # Time budget
        budget = TimeBudgetController(
            total_seconds=self._total_budget,
            table_count=len(snapshot.tables),
        )

        # Step 3: per-subgraph validate → repair → heal
        # Include connection target so the YAML is directly fillable by
        # ``sqlseed fill --config <yaml>`` without requiring --db on the
        # command line. Inserted before "tables" for readability.
        config: dict[str, Any] = {}
        if self._url:
            config["url"] = self._url
        elif self._db_path:
            config["db_path"] = self._db_path
        config["tables"] = []
        for sg_idx, sg_tables in enumerate(subgraphs, 1):
            if budget.is_expired():
                logger.warning(
                    "Time budget expired, falling back to defaults",
                    remaining_tables=sg_tables,
                )
                if self._verbose:
                    _debug(f"[ai-analyze]   TIME BUDGET EXPIRED for {sg_tables} — using defaults")
                self._append_default_columns(config, sg_tables, snapshot)
                continue

            if self._verbose:
                _debug(f"[ai-analyze] Step 3[{sg_idx}/{len(subgraphs)}]: building config for {sg_tables} ...")
            sg_config = self._build_subgraph_config(sg_tables, snapshot)
            violations = self._validate(sg_config, snapshot)
            if self._verbose:
                _debug(f"[ai-analyze]   initial violations={len(violations) if violations else 0} tables={sg_tables}")
                if violations:
                    for v in violations[:5]:
                        _debug(
                            f"[ai-analyze]     - {getattr(v, 'table', '?')}.{getattr(v, 'column', '?')}: "
                            f"{getattr(v, 'message', str(v))}"
                        )
            if not violations:
                config["tables"].extend(sg_config["tables"])
                if self._verbose:
                    _debug("[ai-analyze]   no violations — accepted as-is")
                continue
            # Layer 3 + Layer 4: repair + heal
            if self._verbose:
                _debug("[ai-analyze]   invoking Layer 3 (repair) + Layer 4 (LLM heal) ...")
            result = self._heal_subgraph(sg_config, sg_tables, violations, snapshot, original_hash, budget)
            config["tables"].extend(result.get("tables", []))
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

        # Step 4: post-repair broken edges (Section 14)
        if broken_edges:
            if self._verbose:
                _debug(f"[ai-analyze] Step 4: repairing {len(broken_edges)} broken FK edges ...")
            aligner = BrokenEdgeAligner()
            config = aligner.align(config, broken_edges)
        elif self._verbose:
            _debug("[ai-analyze] Step 4: no broken FK edges to repair")

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
            table_name = tcfg.get("name", "")
            meta = snapshot.tables.get(table_name)
            for c in tcfg.get("columns", []):
                gen = c.get("generator")
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
                if gen in {"?", ""}:
                    gen = None
                    c.pop("generator", None)
                # Derived-mode columns (``derive_from`` + ``expression``) are
                # mutually exclusive with source-mode (``generator`` +
                # ``params``) per the ``ColumnConfig`` model validator.
                # Skip generator inference AND param stripping for derived
                # columns — otherwise we'd add a ``generator`` to a column
                # that already has ``derive_from`` and trigger a Pydantic
                # ValidationError when the YAML is loaded downstream.
                has_derive = bool(c.get("derive_from"))

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
                    has_arith = any(
                        pat in expr_str
                        for pat in ("value +", "value -", "value *", "value/", "timedelta")
                    )
                    if has_arith:
                        col_name_55 = c.get("name", "")
                        src_col_55 = c.get("derive_from", "")
                        if (
                            _has_like_constraint(col_name_55, meta.constraints)
                            or _has_like_constraint(src_col_55, meta.constraints)
                        ):
                            c.pop("derive_from", None)
                            c.pop("expression", None)
                            has_derive = False

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
                    gen = "template"
                    params = c["params"]
                    continue

                params = c.get("params") or {}
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
                        gen = spec.generator_name
                        if gen == "skip":
                            gen = _placeholder_generator(col_type)
                        if gen == "string" and _is_date_column(col_name):
                            gen = "datetime"
                    if gen:
                        c["generator"] = gen

                # Re-infer params from CHECK constraints when the LLM strips
                # them. The LLM sometimes returns ``params: {}`` for columns
                # that have range CHECKs (e.g., ``latitude >= -90.0 AND
                # latitude <= 90.0``), causing fill-time CHECK violations.
                # Re-run the deterministic single-column inference to recover
                # the bounds. Applied when:
                #   - column is in source mode (no ``derive_from``)
                #   - LLM provided a generator but no params
                # Two outcomes:
                #   1. inferred generator matches LLM's → apply inferred params
                #      (e.g., both agree on ``integer``, recover min/max_value)
                #   2. inferred generator is ``boolean`` or ``choice`` (from an
                #      ``IN (...)`` constraint) but LLM picked ``integer`` →
                #      override BOTH generator and params. The ``IN`` constraint
                #      is very specific: ``col IN (0, 1)`` MUST use ``boolean``,
                #      ``col IN ('a', 'b')`` MUST use ``choice``. An ``integer``
                #      generator would produce values outside the allowed set.
                if not has_derive and gen and not params and meta is not None:
                    col_name = c.get("name", "")
                    if col_name in meta.columns:
                        inferred = _infer_from_check_constraints(col_name, meta.constraints, meta.columns)
                        if inferred is not None:
                            inf_gen, inf_params = inferred
                            if inf_gen == gen and inf_params:
                                # Case 1: generators agree — apply params
                                c["params"] = inf_params
                                params = inf_params
                            elif inf_gen in ("boolean", "choice") and gen != inf_gen:
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
                # currently have ``derive_from``, and (c) do NOT have
                # ``null_ratio=1.0`` (always-NULL is also valid for IS NULL
                # OR ... CHECKs — don't override). The re-inferred derive_from
                # takes priority over the LLM's plain generator because it
                # guarantees CHECK compliance.
                if not has_derive and meta is not None and c.get("null_ratio", 0) < 1.0:
                    col_name = c.get("name", "")
                    if col_name in meta.columns:
                        col_type = meta.column_types.get(col_name, "TEXT")
                        # Rebuild fk_cols_set for this table (needed by
                        # _infer_cross_column_config for Pattern 30).
                        fk_cols_set_55: set[str] = set()
                        for fk in meta.foreign_keys:
                            for fc in fk.get("columns", []):
                                fk_cols_set_55.add(fc)
                        cross_result = _infer_cross_column_config(
                            col_name, meta.constraints, meta.columns, col_type, fk_cols_set_55
                        )
                        if cross_result is not None and "derive_from" in cross_result:
                            # Restore derive_from — remove any source-mode keys
                            # that the LLM set (generator, params) to avoid
                            # Pydantic ValidationError (mutual exclusivity).
                            c.pop("generator", None)
                            c.pop("params", None)
                            c.update(cross_result)
                            has_derive = True

                # Strip invalid params (only for source-mode columns)
                if isinstance(params, dict) and gen and not has_derive:
                    c["params"] = _strip_invalid_params(params, gen)

                # UNIQUE + LENGTH(col) = N safety net:
                # Even if the LLM correctly provided ``string`` with
                # min_length=N, max_length=N, the unique adjuster will
                # increase max_length to guarantee uniqueness, breaking the
                # CHECK constraint. Convert to ``pattern`` with
                # ``[A-Za-z0-9]{N}`` which the unique adjuster does NOT
                # touch (uniqueness handled by ConstraintSolver backtracking).
                if not has_derive and gen == "string" and meta is not None:
                    col_name = c.get("name", "")
                    if col_name in meta.columns:
                        unique_cols_set = _get_unique_columns(meta.constraints)
                        if col_name in unique_cols_set:
                            exact_n = _get_exact_length_check(col_name, meta.constraints)
                            if exact_n is not None:
                                c["generator"] = "pattern"
                                c["params"] = {"regex": f"[A-Za-z0-9]{{{exact_n}}}"}
                                gen = "pattern"
                                params = c["params"]

        # Step 6: emit YAML
        if self._verbose:
            table_count = len(config.get("tables", []))
            _debug(f"[ai-analyze] Step 6: emitting YAML ({table_count} tables) ...")
        yaml_str: str = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
        return yaml_str

    def _build_fk_graph(self, snapshot: SchemaSnapshot) -> dict[str, list[str]]:
        """Build FK adjacency list from snapshot.

        Each ``TableMeta.foreign_keys`` entry has keys ``columns``,
        ``ref_table``, ``ref_columns``. Edge direction: source table →
        referenced (parent) table.
        """
        graph: dict[str, list[str]] = {t: [] for t in snapshot.tables}
        for table_name, meta in snapshot.tables.items():
            for fk in meta.foreign_keys:
                ref_table = fk.get("ref_table")
                if ref_table:
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
            meta = snapshot.tables.get(table_name)
            if meta is None:
                continue
            unique_cols = _get_unique_columns(meta.constraints)
            # Extract FK column names for this table. Used by
            # ``_infer_cross_column_config`` to detect FK columns and return
            # None (instead of 0) for nullable FK columns in Pattern 30.
            # FK columns like ``manager_id`` (self-referencing) or
            # ``customer_id`` should never receive a literal ``0`` value
            # because auto-increment IDs start from 1.
            fk_cols_set: set[str] = set()
            # Detect self-referencing FK columns (e.g., categories.parent_id
            # → categories.id). At fill time, the SharedPool for the current
            # table is empty (no rows inserted yet), so foreign_key_or_integer
            # falls back to random integers that don't match any existing PK
            # — causing FK violations. These columns get null_ratio=1.0 in
            # Step 0 below to ensure all values are NULL.
            self_ref_fk_cols: set[str] = set()
            for fk in meta.foreign_keys:
                for c in fk.get("columns", []):
                    fk_cols_set.add(c)
                if fk.get("ref_table") == table_name:
                    for c in fk.get("columns", []):
                        self_ref_fk_cols.add(c)
            cols: list[dict[str, Any]] = []
            for col_name in meta.columns:
                col_type = meta.column_types.get(col_name, "TEXT")
                # Step 0: Self-referencing FK → null_ratio=1.0 (always NULL).
                # This must run BEFORE all other steps because the parent
                # table (same as current) has no rows at fill time, making
                # any non-NULL value an FK violation. Setting null_ratio=1.0
                # is the only safe option for self-referencing FKs during
                # initial bulk fill.
                if col_name in self_ref_fk_cols:
                    cols.append({
                        "name": col_name,
                        "generator": "foreign_key_or_integer",
                        "params": {},
                        "null_ratio": 1.0,
                    })
                    continue
                # Step 1: Try cross-column CHECK inference FIRST.
                # Cross-column constraints (e.g., ``unit_price > cost_price``)
                # are stronger than single-column constraints (e.g.,
                # ``unit_price > 0``) and must take priority: if the column
                # has both, derive_from captures the cross-column relation
                # while a bare min_value would silently drop it.
                cross_config = _infer_cross_column_config(
                    col_name, meta.constraints, meta.columns, col_type, fk_cols_set
                )
                if cross_config is not None:
                    cols.append({"name": col_name, **cross_config})
                    continue
                # Step 2: Try single-column CHECK inference (enum/boolean/range)
                inferred = _infer_from_check_constraints(col_name, meta.constraints, meta.columns)
                if inferred is not None:
                    gen, params = inferred
                    # If column type is REAL/FLOAT but inferred generator is
                    # integer (because CHECK used integer literals like
                    # ``salary > 0``), upgrade to float to match column type.
                    if gen == "integer" and any(
                        k in col_type.upper() for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")
                    ):
                        gen = "float"
                    # UNIQUE + LENGTH(col) = N conflict resolution:
                    # The ``string`` generator with min_length=N, max_length=N
                    # would be broken by the unique adjuster, which increases
                    # max_length to guarantee uniqueness (breaking the CHECK).
                    # Convert to ``pattern`` with ``[A-Za-z0-9]{N}`` — the
                    # pattern generator is NOT adjusted by UniqueAdjuster, and
                    # 62^N combinations (e.g., 3844 for N=2) are sufficient
                    # for typical test data sizes with ConstraintSolver
                    # backtracking handling collisions.
                    if (
                        gen == "string"
                        and col_name in unique_cols
                        and "min_length" in params
                        and "max_length" in params
                        and params["min_length"] == params["max_length"]
                    ):
                        n = params["min_length"]
                        cols.append(
                            {
                                "name": col_name,
                                "generator": "pattern",
                                "params": {"regex": f"[A-Za-z0-9]{{{n}}}"},
                            }
                        )
                        continue
                    # Phone-like column + LENGTH(col) = N → pattern with
                    # [0-9]{N}. The ``string`` generator produces alphanumeric
                    # gibberish for phone columns (semantically wrong even
                    # though it satisfies LENGTH). Using ``pattern`` with
                    # digits-only regex produces phone-like output AND satisfies
                    # the LENGTH CHECK. This avoids triggering the contract
                    # matrix's ``string`` on ``phone`` → ``semantic_upgrade``
                    # rule, which would drop the length params and cause LLM
                    # oscillation between ``string`` (satisfies LENGTH but
                    # semantically wrong) and ``phone`` (semantically correct
                    # but violates LENGTH).
                    if (
                        gen == "string"
                        and _is_phone_like(col_name)
                        and "min_length" in params
                        and "max_length" in params
                        and params["min_length"] == params["max_length"]
                    ):
                        n = params["min_length"]
                        cols.append(
                            {
                                "name": col_name,
                                "generator": "pattern",
                                "params": {"regex": f"[0-9]{{{n}}}"},
                            }
                        )
                        continue
                    cols.append({"name": col_name, "generator": gen, "params": params})
                    continue
                # Step 3: UNIQUE column detection — use template/email generator
                # to guarantee uniqueness. The ``string`` generator produces
                # random strings that collide (birthday paradox: ~350 rows
                # with 8-char strings have ~50% collision probability).
                if col_name in unique_cols:
                    unique_config = _infer_unique_column_config(col_name, col_type)
                    if unique_config is not None:
                        cols.append({"name": col_name, **unique_config})
                        continue
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
                spec = _get_column_mapper().map_column(col_info)
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
                cols.append(col_entry)
            sg_config["tables"].append({"name": table_name, "columns": cols})
        return sg_config

    def _append_default_columns(
        self,
        config: dict[str, Any],
        tables: list[str],
        snapshot: SchemaSnapshot,
    ) -> None:
        """Fallback: append default integer columns for tables skipped due to time budget."""
        for table_name in tables:
            meta = snapshot.tables.get(table_name)
            if meta is None:
                continue
            cols = [{"name": c, "generator": "integer", "params": {}} for c in meta.columns]
            config["tables"].append({"name": table_name, "columns": cols})

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
            remaining = self._validate(sg_config, snapshot)
            if not remaining:
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


def _placeholder_generator(col_type: str) -> str:
    """Pick a sensible placeholder generator based on column type."""
    t = col_type.upper()
    if any(k in t for k in ("INT", "BIGINT", "SMALLINT", "TINYINT")):
        return "integer"
    if any(k in t for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")):
        return "float"
    if any(k in t for k in ("TIMESTAMP", "DATETIME", "DATE", "TIME")):
        return "datetime"
    if "BOOLEAN" in t:
        return "boolean"
    return "string"


def _range_expr_for_op(op: str, x: float) -> str:
    """Build a ``random_float(...)`` expression that satisfies ``col OP x``.

    Used by Pattern 27 (N-way conditional range) to emit per-clause random
    expressions. The lower bound uses 0.01 (not 0) to avoid generating
    exactly 0 for columns that may have ``col > 0`` constraints elsewhere.

    Args:
        op: One of ``<=``, ``<``, ``>=``, ``>``.
        x: The numeric bound from the CHECK clause.

    Returns:
        A Python expression string like ``"random_float(0.01, 10.0)"``.
    """
    if op == "<=":
        return f"random_float(0.01, {x})"
    if op == "<":
        # Strict < — subtract epsilon so the generator never produces x.
        return f"random_float(0.01, {max(x - 0.01, 0.02)})"
    if op == ">=":
        return f"random_float({x}, {x + 100.0})"
    if op == ">":
        # Strict > — add epsilon so the generator never produces x.
        return f"random_float({x + 0.01}, {x + 100.0})"
    # Fallback (shouldn't happen — Pattern 27 only accepts the 4 ops above).
    return f"random_float(0.01, {x})"


def _is_date_column(col_name: str) -> bool:
    """Check if a column name suggests a date/time value.

    SQLite stores dates as TEXT, so column type alone is insufficient.
    This detects common date/time naming conventions:
    - ``*_at`` (created_at, paid_at, ordered_at)
    - ``*_date`` (hire_date, transfer_date)
    - ``*_time`` (start_time, end_time)
    - ``*_on`` (acted_on, published_on)
    - ``check_in`` / ``check_out``
    - ``date_*`` (date_of_birth)
    - ``dob``, ``created``, ``updated``, ``deleted``
    """
    n = col_name.lower()
    if n.endswith(("_at", "_date", "_time", "_on")):
        return True
    if "check_in" in n or "check_out" in n:
        return True
    if n in ("created", "updated", "deleted", "dob"):
        return True
    return bool(n.startswith(("date_", "time_")))


def _like_to_regex(like_pattern: str) -> str:
    """Convert a SQL LIKE pattern to an anchored regex, preserving literal positions.

    SQL LIKE wildcards: ``_`` matches any single char, ``%`` matches zero+ chars.
    Only ``_`` (fixed-length) is supported — ``%`` must be filtered by the caller.

    Each ``_`` becomes ``[A-Za-z0-9]`` (consecutive runs grouped into ``{N}``),
    and literal characters are escaped with ``re.escape`` IN PLACE. This preserves
    the position of literals — critical for patterns like ``__:__`` (HH:MM time
    strings) where the colon must stay at index 2, not collapse to the start.

    Examples:
        ``__:__``  → ``^[A-Za-z0-9]{2}:[A-Za-z0-9]{2}$``
        ``#______`` → ``^#[A-Za-z0-9]{6}$``
        ``PROD-___`` → ``^PROD\\-[A-Za-z0-9]{3}$``
    """
    parts: list[str] = []
    underscore_run = 0
    for ch in like_pattern:
        if ch == "_":
            underscore_run += 1
        else:
            if underscore_run > 0:
                parts.append(f"[A-Za-z0-9]{{{underscore_run}}}" if underscore_run > 1 else "[A-Za-z0-9]")
                underscore_run = 0
            parts.append(re.escape(ch))
    if underscore_run > 0:
        parts.append(f"[A-Za-z0-9]{{{underscore_run}}}" if underscore_run > 1 else "[A-Za-z0-9]")
    return "^" + "".join(parts) + "$"


def _has_like_constraint(col_name: str, constraints: list[dict[str, Any]]) -> bool:
    """Check if a column has a LIKE CHECK constraint (formatted string column).

    A column with ``CHECK (col LIKE 'pattern')`` stores formatted strings
    (e.g., ``start_time LIKE '__:__'`` for "HH:MM" time strings). Such columns
    are NOT real datetimes — ``timedelta`` arithmetic on their string values
    fails at fill time with ``TypeError: can only concatenate str (not
    "datetime.timedelta") to str``.
    """
    col_re = re.escape(col_name)
    for c in constraints:
        if c.get("type") != "check":
            continue
        expr = c.get("expression", "")
        if re.search(rf"{col_re}\s+LIKE\s+", expr, re.IGNORECASE):
            return True
    return False


def _get_unique_columns(constraints: list[dict[str, Any]]) -> set[str]:
    """Extract the set of column names that have a UNIQUE constraint.

    Covers both single-column and composite UNIQUE constraints. For composite
    UNIQUE, all member columns are included (individual column uniqueness is
    not guaranteed, but the template generator is still the safest default).
    """
    unique_cols: set[str] = set()
    for c in constraints:
        if c.get("type") != "unique":
            continue
        cols_list = c.get("columns") or []
        unique_cols.update(cols_list)
    return unique_cols


def _get_exact_length_check(
    col_name: str,
    constraints: list[dict[str, Any]],
) -> int | None:
    """Return N if the column has a ``LENGTH(col) = N`` CHECK constraint.

    Returns ``None`` if no such exact-length CHECK exists. Only matches the
    strict equality form — ``LENGTH(col) >= N`` or ``<= N`` are handled by
    the ``string`` generator's min_length/max_length and do not conflict
    with the unique adjuster (only exact length is at risk because the
    adjuster may increase max_length to guarantee uniqueness).
    """
    col = re.escape(col_name)
    for c in constraints:
        if c.get("type") != "check":
            continue
        expr = c.get("expression", "")
        if not expr:
            continue
        m = re.match(
            rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*=\s*(\d+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            return int(m.group(1))
    return None


def _infer_unique_column_config(
    col_name: str,
    col_type: str,
) -> dict[str, Any] | None:
    """Infer a uniqueness-guaranteeing config for a UNIQUE column.

    Returns a config dict with a ``template`` or ``email`` generator, or
    ``None`` if the column type is not text-like (numeric UNIQUE columns
    rely on the ConstraintSolver's backtracking for uniqueness).

    - Email columns (name contains "email"): ``email`` generator (Faker
      produces unique-enough emails for typical test data sizes).
    - Other text UNIQUE columns: ``template`` generator with a sequence
      pattern ``{PREFIX}-{sequence:04d}`` derived from the column name.
    """
    t = col_type.upper()
    is_text = any(k in t for k in ("VARCHAR", "TEXT", "CHAR", "CLOB"))
    if not is_text:
        return None
    if "email" in col_name.lower():
        return {"generator": "email", "params": {}}
    prefix = col_name.upper()[:8]
    return {
        "generator": "template",
        "params": {"template": f"{prefix}-{{sequence:04d}}"},
    }


def _infer_from_check_constraints(
    col_name: str,
    constraints: list[dict[str, Any]],
    all_columns: list[str] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Infer generator + params from CHECK constraints for a single column.

    Returns ``(generator_name, params)`` tuple, or ``None`` if no inference
    is possible. Handles:
    - ``col IN ('a', 'b', 'c')`` → choice generator (string enum)
    - ``col IN (0, 1)`` → boolean generator
    - ``col IN (1, 2, 3)`` → choice generator (numeric enum)
    - ``col >= X AND col <= Y`` → integer/float with min_value/max_value
    - ``col > X AND col < Y`` → integer/float with exclusive bounds
    - ``col >= X`` / ``col > X`` → integer/float with min_value
    - ``col <= Y`` / ``col < Y`` → integer/float with max_value

    Cross-column constraints (involving multiple columns) are skipped —
    those are handled by ``derive_from`` at Layer 4.

    Multi-CHECK merging: when a column has MULTIPLE single-column CHECK
    constraints (e.g., ``col >= 0`` as one CHECK and ``col <= 1000`` as
    another), the bounds are MERGED into a single range. Previously, the
    function returned on the first match, silently dropping the second
    bound — causing CHECK violations at fill time (e.g., generating
    ``low_stock_threshold = 5000`` when ``<= 1000`` was also required).
    Enum/format patterns (choice, boolean, pattern) are returned
    immediately on first match since they are mutually exclusive with
    range patterns.
    """
    # Collect all parsed results from matching single-column CHECKs.
    # Range/length patterns are merged; enum/format patterns return
    # immediately (they are mutually exclusive with other patterns).
    merged_gen: str | None = None
    merged_params: dict[str, Any] = {}
    for c in constraints:
        if c.get("type") != "check":
            continue
        expr = c.get("expression", "")
        if not expr:
            continue
        # Check if col_name appears in the expression as a word-boundary match
        if not re.search(rf"\b{re.escape(col_name)}\b", expr, re.IGNORECASE):
            continue
        # If all_columns provided, verify this is NOT a cross-column constraint
        # (no other column name from the table appears in the expression).
        if all_columns:
            other_cols = [oc for oc in all_columns if oc != col_name]
            is_cross_column = False
            for other in other_cols:
                if re.search(rf"\b{re.escape(other)}\b", expr, re.IGNORECASE):
                    is_cross_column = True
                    break
            if is_cross_column:
                continue
        # Try to parse as single-column CHECK
        result = _parse_single_column_check(col_name, expr)
        if result is None:
            continue
        gen, params = result
        # Enum/format patterns are mutually exclusive — return immediately.
        # These patterns fully constrain the column's value space, so merging
        # with a subsequent range pattern would be incorrect.
        if gen in ("choice", "boolean", "pattern"):
            return result
        # Range patterns (integer/float with min_value/max_value) and
        # length patterns (string with min_length/max_length) are MERGED
        # across multiple CHECKs. Take the tighter bound on each side:
        # - min_value/min_length: take the MAX (higher lower bound)
        # - max_value/max_length: take the MIN (lower upper bound)
        if merged_gen is None:
            merged_gen = gen
            merged_params = dict(params)
        else:
            # Type promotion: if either bound is float, promote to float.
            if gen == "float" and merged_gen == "integer":
                merged_gen = "float"
                # Convert existing int bounds to float
                for k in ("min_value", "max_value"):
                    if k in merged_params and isinstance(merged_params[k], int):
                        merged_params[k] = float(merged_params[k])
            # Merge min_value (take the higher/larger lower bound)
            if "min_value" in params:
                new_min = params["min_value"]
                if "min_value" in merged_params:
                    merged_params["min_value"] = max(merged_params["min_value"], new_min)
                else:
                    merged_params["min_value"] = new_min
            # Merge max_value (take the smaller/lower upper bound)
            if "max_value" in params:
                new_max = params["max_value"]
                if "max_value" in merged_params:
                    merged_params["max_value"] = min(merged_params["max_value"], new_max)
                else:
                    merged_params["max_value"] = new_max
            # Merge min_length (take the larger lower bound)
            if "min_length" in params:
                new_min = params["min_length"]
                if "min_length" in merged_params:
                    merged_params["min_length"] = max(merged_params["min_length"], new_min)
                else:
                    merged_params["min_length"] = new_min
            # Merge max_length (take the smaller upper bound)
            if "max_length" in params:
                new_max = params["max_length"]
                if "max_length" in merged_params:
                    merged_params["max_length"] = min(merged_params["max_length"], new_max)
                else:
                    merged_params["max_length"] = new_max
    if merged_gen is not None:
        return (merged_gen, merged_params)
    return None


def _parse_single_column_check(
    col_name: str,
    expr: str,
) -> tuple[str, dict[str, Any]] | None:
    """Parse a single-column CHECK expression and return (generator, params).

    Returns ``None`` if the expression doesn't match any known pattern.
    All patterns are case-insensitive and tolerate arbitrary whitespace.

    Handled patterns:
    - ``LENGTH(col) >= N`` / ``> N`` → string with ``min_length``
    - ``LENGTH(col) = N`` → string with ``min_length`` and ``max_length``
    - ``LENGTH(col) <= N`` / ``< N`` → string with ``max_length``
    - ``col LIKE '<literal>____' AND LENGTH(col) = N`` → pattern with regex
      ``^<literal>[A-Za-z0-9]{underscore_count}$`` (fixed-length code format)
    - ``LENGTH(col) = N AND col LIKE '<literal>____'`` → same as above (reversed)
    - ``col LIKE '<literal>____'`` → pattern with regex (standalone, no LENGTH)
    - ``col IN ('a', 'b', 'c')`` → choice generator (string enum)
    - ``col IN (0, 1)`` → boolean generator
    - ``col IN (1, 2, 3)`` → choice generator (numeric enum)
    - ``col BETWEEN X AND Y`` → integer/float with inclusive bounds
    - ``col >= X AND col <= Y`` → inclusive range
    - ``col > X AND col < Y`` → exclusive range
    - ``col > X AND col <= Y`` / ``col >= X AND col < Y`` → mixed range
    - ``col >= X`` / ``col > X`` → lower bound only
    - ``col <= Y`` / ``col < Y`` → upper bound only
    - ``col != 0`` → integer/float with ``min_value=1`` (or ``0.01`` for float)
    - ``col IS NULL OR <inner_expr>`` → strip prefix, parse inner expression
      (always generating a valid non-NULL value satisfies the CHECK)
    """
    col = re.escape(col_name)

    # Strip "col IS NULL OR ..." prefix (conditional NULL with inner constraint).
    # e.g., "phone IS NULL OR LENGTH(phone) = 11" → "LENGTH(phone) = 11"
    # e.g., "health_factor IS NULL OR (health_factor >= 1 AND health_factor <= 10)"
    #       → "health_factor >= 1 AND health_factor <= 10"
    # When the column CAN be NULL, always generating a valid non-NULL value
    # satisfies the CHECK (NULL is allowed but not required). This defers
    # to the inner expression's pattern matching.
    m_null_prefix = re.match(
        rf"^\s*{col}\s+IS\s+NULL\s+OR\s+(.+)$",
        expr,
        re.IGNORECASE,
    )
    if m_null_prefix:
        inner = m_null_prefix.group(1).strip()
        # Strip surrounding parentheses if present (e.g., "(col >= 1 AND col <= 10)")
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1].strip()
        result = _parse_single_column_check(col_name, inner)
        if result is not None:
            return result

    # Pattern: LENGTH(col) >= N — minimum length constraint
    # e.g., LENGTH(name) >= 2
    # Uses pystr_min_length / pystr_max_length from Faker's pystr generator.
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*>=\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"min_length": n})

    # Pattern: LENGTH(col) > N — strictly greater than N
    # e.g., LENGTH(code) > 3 → min_length = 4
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*>\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"min_length": n + 1})

    # Pattern: LENGTH(col) = N — exact length
    # e.g., LENGTH(cvv) = 3 → both min and max length = 3
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*=\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"min_length": n, "max_length": n})

    # Pattern: LENGTH(col) <= N — maximum length constraint
    # e.g., LENGTH(description) <= 500
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*<=\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"max_length": n})

    # Pattern: LENGTH(col) < N — strictly less than N
    # e.g., LENGTH(label) < 20 → max_length = 19
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*<\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        return ("string", {"max_length": n - 1})

    # Pattern: col LIKE '<literal>____' AND LENGTH(col) = N
    # e.g., color_code LIKE '#______' AND LENGTH(color_code) = 7
    # → pattern generator with regex ^<literal>[A-Za-z0-9]{underscore_count}$
    #
    # SQL LIKE wildcards: ``_`` matches any single char, ``%`` matches zero
    # or more chars. We only handle patterns where all wildcards are ``_``
    # (fixed-length), because ``%`` makes the length variable. Combined
    # with ``LENGTH(col) = N``, this constrains both the prefix and the
    # total length. The alphanumeric charset is the safest default for
    # code-style columns; users can override with a custom config for
    # specific charsets (e.g., hex for color codes).
    m = re.match(
        rf"^\s*{col}\s+LIKE\s+'([^']*)'\s+AND\s+LENGTH\s*\(\s*{col}\s*\)\s*=\s*(\d+)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        like_pattern = m.group(1)
        total_len = int(m.group(2))
        if "%" not in like_pattern and like_pattern.count("_") > 0 and len(like_pattern) == total_len:
            regex = _like_to_regex(like_pattern)
            return ("pattern", {"regex": regex})

    # Pattern: LENGTH(col) = N AND col LIKE '<literal>____' (reversed order)
    m = re.match(
        rf"^\s*LENGTH\s*\(\s*{col}\s*\)\s*=\s*(\d+)\s+AND\s+{col}\s+LIKE\s+'([^']*)'\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        total_len = int(m.group(1))
        like_pattern = m.group(2)
        if "%" not in like_pattern and like_pattern.count("_") > 0 and len(like_pattern) == total_len:
            regex = _like_to_regex(like_pattern)
            return ("pattern", {"regex": regex})

    # Pattern: col LIKE '<literal>____' (standalone, no LENGTH)
    # Infer length from underscore count alone. Only handle when all
    # wildcards are ``_`` (fixed-length); ``%`` is skipped because the
    # variable length cannot be deterministically generated.
    m = re.match(
        rf"^\s*{col}\s+LIKE\s+'([^']*)'\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        like_pattern = m.group(1)
        if "%" not in like_pattern and like_pattern.count("_") > 0:
            regex = _like_to_regex(like_pattern)
            return ("pattern", {"regex": regex})

    # Pattern: col IN ('a', 'b', 'c') — string enum
    m = re.match(
        rf"^\s*{col}\s+IN\s*\(\s*('[^']*'(?:\s*,\s*'[^']*')*)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        choices_str = m.group(1)
        choices = re.findall(r"'([^']*)'", choices_str)
        if choices:
            return ("choice", {"choices": choices})

    # Pattern: col IN (0, 1) or col IN (1, 0) — boolean
    m = re.match(
        rf"^\s*{col}\s+IN\s*\(\s*(0\s*,\s*1|1\s*,\s*0)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        return ("boolean", {})

    # Pattern: col IN (int, int, ...) — numeric enum (non-boolean)
    m = re.match(
        rf"^\s*{col}\s+IN\s*\(\s*([\d\s,]+)\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        nums_str = m.group(1)
        nums = [int(n.strip()) for n in nums_str.split(",") if n.strip()]
        if len(nums) != 2 or set(nums) != {0, 1}:
            return ("choice", {"choices": nums})

    # Pattern: col BETWEEN X AND Y — inclusive range (SQL BETWEEN syntax)
    # Equivalent to col >= X AND col <= Y, but uses the BETWEEN keyword.
    # Common in DDL generated by ORM tools and manual schema definitions.
    m = re.match(
        rf"^\s*{col}\s+BETWEEN\s+(-?\d+(?:\.\d+)?)\s+AND\s+(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        min_str, max_str = m.group(1), m.group(2)
        is_int = "." not in min_str and "." not in max_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(min_str), "max_value": int(max_str)})
        return (gen, {"min_value": float(min_str), "max_value": float(max_str)})

    # Pattern: col >= X AND col <= Y — inclusive range
    m = re.match(
        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        min_str, max_str = m.group(1), m.group(2)
        is_int = "." not in min_str and "." not in max_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(min_str), "max_value": int(max_str)})
        return (gen, {"min_value": float(min_str), "max_value": float(max_str)})

    # Pattern: col > X AND col < Y — exclusive range (both bounds strict)
    # For integers: shift min up by 1, max down by 1.
    # For floats: add/subtract epsilon (0.01) to both bounds (see comment
    # in the ``col > X AND col <= Y`` pattern above for rationale).
    m = re.match(
        rf"^\s*{col}\s*>\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        min_str, max_str = m.group(1), m.group(2)
        is_int = "." not in min_str and "." not in max_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(min_str) + 1, "max_value": int(max_str) - 1})
        return (gen, {"min_value": float(min_str) + 0.01, "max_value": float(max_str) - 0.01})

    # Pattern: col > X AND col <= Y — mixed range (exclusive lower, inclusive upper)
    # e.g., interest_rate > 0 AND interest_rate <= 0.3
    # e.g., rate > 0.0 AND rate <= 0.25
    # For integers: shift min up by 1 (X+1) to satisfy strict inequality.
    # For floats: add epsilon (0.01) to min_value. ``random.uniform(X, Y)``
    # CAN return X (both endpoints are inclusive in Python), which would
    # violate the strict ``> X`` CHECK. ConstraintSolver does NOT retry
    # CHECK violations (only UNIQUE), so a single 0.0 value aborts the
    # entire fill. Adding 0.01 ensures all generated values are strictly
    # greater than X.
    m = re.match(
        rf"^\s*{col}\s*>\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        min_str, max_str = m.group(1), m.group(2)
        is_int = "." not in min_str and "." not in max_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(min_str) + 1, "max_value": int(max_str)})
        return (gen, {"min_value": float(min_str) + 0.01, "max_value": float(max_str)})

    # Pattern: col >= X AND col < Y — mixed range (inclusive lower, exclusive upper)
    # e.g., score >= 0 AND score < 100
    # For integers: shift max down by 1 (Y-1) to satisfy strict inequality.
    # For floats: subtract epsilon (0.01) from max_value for the same reason
    # as above — ``random.uniform`` can return Y, violating ``< Y``.
    m = re.match(
        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        min_str, max_str = m.group(1), m.group(2)
        is_int = "." not in min_str and "." not in max_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(min_str), "max_value": int(max_str) - 1})
        return (gen, {"min_value": float(min_str), "max_value": float(max_str) - 0.01})

    # Pattern: col >= X — lower bound only (inclusive)
    m = re.match(
        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(val_str)})
        return (gen, {"min_value": float(val_str)})

    # Pattern: col > X — lower bound only (exclusive)
    m = re.match(
        rf"^\s*{col}\s*>\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(val_str) + 1})
        # For floats, the CHECK is strict (>), but ``min_value`` is inclusive
        # (>=). If we set ``min_value = X``, the generator can produce X
        # (e.g., ``random.uniform(0.0, max)`` can return 0.0), which fails
        # the strict ``> X`` CHECK. Add a small epsilon to ensure all
        # generated values are strictly greater than X.
        return (gen, {"min_value": float(val_str) + 0.01})

    # Pattern: col <= Y — upper bound only (inclusive)
    m = re.match(
        rf"^\s*{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"max_value": int(val_str)})
        return (gen, {"max_value": float(val_str)})

    # Pattern: col < Y — upper bound only (exclusive)
    m = re.match(
        rf"^\s*{col}\s*<\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"max_value": int(val_str) - 1})
        # For floats, ``max_value`` is inclusive (<=) but the CHECK is strict
        # (<). Subtract a small epsilon so the generator never produces Y.
        return (gen, {"max_value": float(val_str) - 0.01})

    # Pattern: col != N — inequality with a literal (excludes a single value)
    # e.g., quantity != 0, status != -1
    # For ``col != 0`` (the most common case): generate positive non-zero
    # values by setting min_value=1 (integer) or min_value=0.01 (float).
    # This is a pragmatic choice — most real-world columns with ``!= 0``
    # (quantity, count, amount) expect positive values. For ``col != N``
    # where N != 0: skip (cannot reliably exclude a single value from a
    # random range without the choice generator, and guessing a safe range
    # would be arbitrary).
    m = re.match(
        rf"^\s*{col}\s*!=\s*(-?\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        if is_int and int(val_str) == 0:
            return ("integer", {"min_value": 1})
        if not is_int and float(val_str) == 0.0:
            return ("float", {"min_value": 0.01})

    return None


def _infer_cross_column_config(
    col_name: str,
    constraints: list[dict[str, Any]],
    all_columns: list[str],
    col_type: str,
    fk_columns: set[str] | None = None,
) -> dict[str, Any] | None:
    """Infer config from cross-column CHECK constraints.

    Returns a config dict with either:
    - ``derive_from`` + ``expression`` (for derived mode — date/numeric ordering)
    - ``generator`` + ``params`` + ``null_ratio`` (for source mode — always NULL)

    Or ``None`` if no inference is possible.

    The ``fk_columns`` parameter is a set of column names that are foreign
    keys. For FK columns, Pattern 30 returns ``None`` for BOTH branches
    (always NULL) because returning a literal like ``0`` causes FK
    violations (auto-increment IDs start from 1, so 0 is never valid).

    Handled patterns (where ``col`` is ``col_name`` and ``other`` is another column):
    - ``col IS NULL OR col (>=|>) other`` → derive_from other, add timedelta
    - ``col >= other`` (standalone) → derive_from other, add timedelta/offset
    - ``col > other`` (standalone) → derive_from other, multiply by factor > 1
    - ``col <= other`` (standalone) → derive_from other, multiply by factor <= 1
    - ``col < other`` (standalone) → derive_from other, multiply by factor < 1
    - ``col IS NULL OR col = expr`` → null_ratio=1.0 (computed columns)
    - ``col IS NULL OR other = 'value'`` → null_ratio=1.0 (conditional NULL)
    - ``col != other`` (integer inequality — safe ternary offset)
    - ``col >= col1 * col2`` (arithmetic — derive_from col1, reference col2)
    - ``col = col1 (+|-|*) col2`` (arithmetic equality — derive_from col1, reference col2)
    - ``col = col1 + col2 + col3`` (three-column addition — derive_from col1, reference col2 + col3)
    - ``col = abs(col1) (+|-|*) col2`` (abs first operand — derive_from col1, expression uses abs(value))
    - ``col = col1 (+|-|*) abs(col2)`` (abs second operand — derive_from col1, expression uses abs(row[col2]))
    - ``col = abs(col1) * abs(col2)`` (abs both operands — derive_from col1, expression uses abs() on both)
    - ``col = abs(col1)`` (standalone abs — derive_from col1, expression abs(value))
    - ``col >= X AND col <= other`` (compound — literal lower + column upper)
    - ``col >= other AND col <= Y`` (compound — column lower + literal upper)
    - ``col > X AND col < other`` (compound — exclusive literal lower + exclusive column upper)
    - ``col > other AND col < Y`` (compound — exclusive column lower + exclusive literal upper)
    - ``col != VALUE OR other_col = VALUE2`` (conditional equality — derive col from other_col)
    - ``col1 + col2 = col`` (reverse sum equality — derive addend from total)
    - ``col = VALUE OR other_col < col2 OR other_col > col3`` (range membership — derive col from other_col's range)
    - ``col = (col1 + col2 [+ col3]) / N`` (average of N columns — derive from col1, reference others)
    - ``col <= col2 * CONSTANT`` (percentage/scalar upper bound — derive from col2)

    Skipped patterns (not safely inferable from CHECK alone):
    - ``col != other`` for non-integer columns (needs FK pool awareness)
    """
    col = re.escape(col_name)
    col_set = set(all_columns)
    is_date_type = any(k in col_type.upper() for k in ("DATE", "TIME", "DATETIME"))
    # SQLite stores dates as TEXT, so also check column name patterns.
    is_date_col = is_date_type or _is_date_column(col_name)
    # Formatted string columns (with LIKE constraints, e.g., ``start_time LIKE
    # '__:__'``) are NOT real datetimes or numbers — they store formatted
    # strings like "HH:MM". ANY ``derive_from`` expression that does
    # arithmetic on such a column's value (``value + ...``, ``value * ...``,
    # ``timedelta(...)``) fails at fill time with ``TypeError: can only
    # concatenate str (not X) to str``. Return None immediately so the
    # single-column inference path (which handles LIKE → ``pattern``
    # generator) takes precedence over cross-column derive_from.
    if _has_like_constraint(col_name, constraints):
        return None
    is_float_type = any(k in col_type.upper() for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC"))
    is_int_type = any(k in col_type.upper() for k in ("INT", "BIGINT", "SMALLINT", "TINYINT"))
    # FK columns: returning a literal (e.g., 0) for FK columns causes FK
    # violations because auto-increment IDs start from 1. For nullable FK
    # columns, None (NULL) is always valid. For NOT NULL FK columns, the
    # derive_from approach is insufficient — the LLM or BrokenEdgeAligner
    # must handle FK pool assignment. Here we detect FK columns so Pattern 30
    # can return None for both branches (always NULL).
    is_fk_column = fk_columns is not None and col_name in fk_columns

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
    def _constraint_sort_key(c: dict[str, Any]) -> tuple[int, int]:
        if c.get("type") != "check":
            return (2, 0)
        expr = c.get("expression", "")
        # Conditional constraints (with OR) get priority 0
        if re.search(r"\s+OR\s+", expr, re.IGNORECASE):
            # Secondary: constraints with ``IN (...)`` are more restrictive
            # (they force a specific NULL/value for non-matching cases)
            if re.search(r"\bIN\s*\(", expr, re.IGNORECASE):
                return (0, 0)
            return (0, 1)
        # Compound range constraints (with AND) get priority 1
        return (1, 0)

    for c in sorted(constraints, key=_constraint_sort_key):
        if c.get("type") != "check":
            continue
        expr = c.get("expression", "")
        if not expr:
            continue
        # Check if col_name appears in the expression
        if not re.search(rf"\b{col}\b", expr, re.IGNORECASE):
            continue
        # Check if any other column appears (cross-column)
        other_cols_in_expr = [
            other
            for other in all_columns
            if other != col_name and re.search(rf"\b{re.escape(other)}\b", expr, re.IGNORECASE)
        ]
        if not other_cols_in_expr:
            continue  # Single-column constraint, handled by _infer_from_check_constraints
        # Skip constraints where any other column has a LIKE constraint —
        # arithmetic on a formatted string (e.g., ``start_time`` storing
        # "HH:MM") fails at fill time. The column should use a ``pattern``
        # generator (from single-column LIKE inference) instead of a
        # ``derive_from`` that does arithmetic on the string value.
        if any(_has_like_constraint(oc, constraints) for oc in other_cols_in_expr):
            continue

        # Pattern 4: col IS NULL OR col = expr (computed column with NULL escape)
        # e.g., line_total IS NULL OR line_total = quantity * unit_price * (1 - discount)
        if re.search(rf"{col}\s+IS\s+NULL\s+OR\s+{col}\s*=", expr, re.IGNORECASE):
            return {
                "generator": _placeholder_generator(col_type),
                "params": {},
                "null_ratio": 1.0,
            }

        # Pattern 5: col IS NULL OR other_col = 'value' (conditional NULL)
        # e.g., completed_at IS NULL OR status = 'completed'
        m = re.search(
            rf"{col}\s+IS\s+NULL\s+OR\s+(\w+)\s*=\s*'([^']*)'",
            expr,
            re.IGNORECASE,
        )
        if m:
            return {
                "generator": _placeholder_generator(col_type),
                "params": {},
                "null_ratio": 1.0,
            }

        # Pattern 1: col IS NULL OR col (>=|>|<=|<) other_col (ordering with NULL escape)
        # Also handles: col IS NULL OR other IS NULL OR col >= other
        # e.g., termination_date IS NULL OR termination_date >= hire_date
        # e.g., due_date IS NULL OR start_date IS NULL OR due_date >= start_date
        # e.g., assessment_price IS NULL OR assessment_price <= listing_price
        # e.g., budget_max IS NULL OR budget_min IS NULL OR budget_max >= budget_min
        # All four comparison operators are handled. For dates, timedelta is
        # used; for floats, multiplication factors; for ints, additive offsets.
        m = re.search(
            rf"{col}\s+IS\s+NULL.*OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
            expr,
            re.IGNORECASE,
        )
        if m:
            op = m.group(1)
            other_col = m.group(2)
            if other_col in col_set and other_col != col_name:
                if is_date_col or _is_date_column(other_col):
                    # Date columns: use timedelta
                    if op in (">=", ">"):
                        return {
                            "derive_from": other_col,
                            "expression": "value + timedelta(days=random_int(1, 365))",
                        }
                    # op in ("<=", "<") — subtract timedelta
                    days = "0" if op == "<=" else "1"
                    return {
                        "derive_from": other_col,
                        "expression": f"value - timedelta(days=random_int({days}, 365))",
                    }
                if is_float_type:
                    # Float columns: use multiplication factors
                    if op == ">=":
                        return {
                            "derive_from": other_col,
                            "expression": "value + random_float(0, 100)",
                        }
                    if op == ">":
                        return {
                            "derive_from": other_col,
                            "expression": "value * random_float(1.01, 2.0)",
                        }
                    if op == "<=":
                        return {
                            "derive_from": other_col,
                            "expression": "value * random_float(0.5, 1.0)",
                        }
                    # op == "<"
                    return {
                        "derive_from": other_col,
                        "expression": "value * random_float(0.5, 0.99)",
                    }
                # Integer columns: use additive offsets
                if op == ">=":
                    return {
                        "derive_from": other_col,
                        "expression": "value + random_int(0, 100)",
                    }
                if op == ">":
                    return {
                        "derive_from": other_col,
                        "expression": "value + random_int(1, 100)",
                    }
                if op == "<=":
                    return {
                        "derive_from": other_col,
                        "expression": "value - random_int(0, 100)",
                    }
                # op == "<"
                return {
                    "derive_from": other_col,
                    "expression": "value - random_int(1, 100)",
                }

        # Pattern 2: col >= other_col (standalone, no NULL escape)
        # e.g., due_date >= invoice_date
        m = re.match(rf"^\s*{col}\s*>=\s*(\w+)\s*$", expr, re.IGNORECASE)
        if m:
            other_col = m.group(1)
            if other_col in col_set and other_col != col_name:
                if is_date_col:
                    return {
                        "derive_from": other_col,
                        "expression": "value + timedelta(days=random_int(1, 30))",
                    }
                if is_float_type:
                    return {
                        "derive_from": other_col,
                        "expression": "value + random_float(1, 100)",
                    }
                return {
                    "derive_from": other_col,
                    "expression": "value + random_int(1, 100)",
                }

        # Pattern 3: col > other_col (standalone comparison — date or numeric)
        # For date columns (e.g., check_out > check_in): use timedelta to
        # guarantee the derived value is strictly greater than the source.
        # For float columns (e.g., unit_price > cost_price): multiply by a
        # factor > 1 to guarantee strict inequality.
        # For int columns: add a positive offset.
        m = re.match(rf"^\s*{col}\s*>\s*(\w+)\s*$", expr, re.IGNORECASE)
        if m:
            other_col = m.group(1)
            if other_col in col_set and other_col != col_name:
                if is_date_col or _is_date_column(other_col):
                    return {
                        "derive_from": other_col,
                        "expression": "value + timedelta(days=random_int(1, 30))",
                    }
                if is_float_type:
                    return {
                        "derive_from": other_col,
                        "expression": "value * random_float(1.1, 2.0)",
                    }
                return {
                    "derive_from": other_col,
                    "expression": "value + random_int(1, 100)",
                }

        # Pattern 8: col <= other_col (standalone — inclusive upper bound)
        # e.g., remaining_balance <= loan_amount, used_count <= total_count
        # For date columns: subtract a non-negative timedelta (0 days = equality).
        # For float columns (positive values): multiply by factor in [0.5, 1.0]
        #   (factor=1.0 gives equality, satisfying <=).
        # For int columns: generate random_int(0, value) — this guarantees
        #   0 <= result <= value, satisfying both col <= other_col AND
        #   col >= 0 (a common companion CHECK). The previous expression
        #   ``value - random_int(0, 100)`` could produce negative values
        #   when value < 100, violating col >= 0 constraints.
        # Note: float multiplication assumes positive source values (typical
        # for money/amount columns). For mixed-sign columns, the
        # ConstraintSolver's retry mechanism handles edge cases.
        m = re.match(rf"^\s*{col}\s*<=\s*(\w+)\s*$", expr, re.IGNORECASE)
        if m:
            other_col = m.group(1)
            if other_col in col_set and other_col != col_name:
                if is_date_col or _is_date_column(other_col):
                    return {
                        "derive_from": other_col,
                        "expression": "value - timedelta(days=random_int(0, 365))",
                    }
                if is_float_type:
                    return {
                        "derive_from": other_col,
                        "expression": "value * random_float(0.5, 1.0)",
                    }
                return {
                    "derive_from": other_col,
                    "expression": "random_int(0, value)",
                }

        # Pattern 8a: col >= X AND col <= other_col (compound — lower bound literal + upper bound column)
        # e.g., remaining_balance >= 0 AND remaining_balance <= loan_amount
        # Derive from other_col, generate a value in [X, other_col] using
        # random_float/random_int with the literal X as min and the derived
        # value (other_col) as max. This guarantees both bounds are satisfied
        # when other_col >= X (typically ensured by other CHECK constraints
        # like loan_amount > 0).
        m = re.match(
            rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            x_str, other_col = m.group(1), m.group(2)
            if other_col in col_set and other_col != col_name:
                if is_float_type:
                    x_val = float(x_str)
                    return {
                        "derive_from": other_col,
                        "expression": f"random_float({x_val}, value)",
                    }
                x_val = int(x_str)
                return {
                    "derive_from": other_col,
                    "expression": f"random_int({x_val}, value)",
                }

        # Pattern 8b: col >= other_col AND col <= Y (compound — lower bound column + upper bound literal)
        # e.g., discount_rate >= min_rate AND discount_rate <= 0.5
        # Derive from other_col, generate a value in [other_col, Y] using
        # random_float/random_int with the derived value as min and literal Y as max.
        m = re.match(
            rf"^\s*{col}\s*>=\s*(\w+)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col, y_str = m.group(1), m.group(2)
            if other_col in col_set and other_col != col_name:
                if is_float_type:
                    y_val = float(y_str)
                    return {
                        "derive_from": other_col,
                        "expression": f"random_float(value, {y_val})",
                    }
                y_val = int(y_str)
                return {
                    "derive_from": other_col,
                    "expression": f"random_int(value, {y_val})",
                }

        # Pattern 8c: col > X AND col < other_col (compound — exclusive lower literal + exclusive upper column)
        # e.g., cost_price > 0 AND cost_price < unit_price
        # Derive from other_col, generate a value in (X, other_col) using
        # random_float/random_int. For floats, exclusive bounds are negligible
        # (probability of hitting exact bound is 0). For integers, shift by 1.
        m = re.match(
            rf"^\s*{col}\s*>\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            x_str, other_col = m.group(1), m.group(2)
            if other_col in col_set and other_col != col_name:
                if is_float_type:
                    x_val = float(x_str)
                    return {
                        "derive_from": other_col,
                        "expression": f"random_float({x_val}, value)",
                    }
                x_val = int(x_str)
                return {
                    "derive_from": other_col,
                    "expression": f"random_int({x_val + 1}, value - 1)",
                }

        # Pattern 8d: col > other_col AND col < Y (compound — exclusive lower column + exclusive upper literal)
        # e.g., end_time > start_time AND end_time < deadline
        # Derive from other_col, generate a value in (other_col, Y).
        m = re.match(
            rf"^\s*{col}\s*>\s*(\w+)\s+AND\s+{col}\s*<\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col, y_str = m.group(1), m.group(2)
            if other_col in col_set and other_col != col_name:
                if is_float_type:
                    y_val = float(y_str)
                    return {
                        "derive_from": other_col,
                        "expression": f"random_float(value, {y_val})",
                    }
                y_val = int(y_str)
                return {
                    "derive_from": other_col,
                    "expression": f"random_int(value + 1, {y_val - 1})",
                }

        # Pattern 8e: col >= X AND col < other_col (compound — inclusive lower literal + exclusive upper column)
        # e.g., deductible >= 0.0 AND deductible < coverage_amount
        # e.g., discount >= 0.0 AND discount < base_price
        # Derive from other_col, generate a value in [X, other_col) — always
        # strictly less than other_col to satisfy the exclusive upper bound.
        # For floats: use value * random_float(0.0, 0.99) when X=0 (common case),
        # or max(X, value * random_float(0.0, 0.99)) when X > 0. The factor 0.99
        # guarantees the result is strictly < value (since 0.99 < 1.0).
        # For integers: use random_int(X, value - 1) — safe when value > X
        # (guaranteed by well-formed schemas where other_col > X).
        m = re.match(
            rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            x_str_8e, other_col_8e = m.group(1), m.group(2)
            if other_col_8e in col_set and other_col_8e != col_name:
                if is_float_type:
                    x_val_8e = float(x_str_8e)
                    if x_val_8e == 0:
                        return {
                            "derive_from": other_col_8e,
                            "expression": "value * random_float(0.0, 0.99)",
                        }
                    return {
                        "derive_from": other_col_8e,
                        "expression": f"max({x_val_8e}, value * random_float(0.0, 0.99))",
                    }
                x_val_8e = int(x_str_8e)
                return {
                    "derive_from": other_col_8e,
                    "expression": f"random_int({x_val_8e}, value - 1)",
                }

        # Pattern 9: col < other_col (standalone — strict upper bound)
        # e.g., transfer_fee < amount
        # For date columns: subtract a positive timedelta (>= 1 day).
        # For float columns (positive values): multiply by factor in [0.1, 0.9]
        #   (always strictly less than source).
        # For int columns: subtract a positive offset (>= 1).
        m = re.match(rf"^\s*{col}\s*<\s*(\w+)\s*$", expr, re.IGNORECASE)
        if m:
            other_col = m.group(1)
            if other_col in col_set and other_col != col_name:
                if is_date_col or _is_date_column(other_col):
                    return {
                        "derive_from": other_col,
                        "expression": "value - timedelta(days=random_int(1, 365))",
                    }
                if is_float_type:
                    return {
                        "derive_from": other_col,
                        "expression": "value * random_float(0.1, 0.9)",
                    }
                return {
                    "derive_from": other_col,
                    "expression": "value - random_int(1, 100)",
                }

        # Pattern 6: col != other_col (inequality between two integer/FK columns)
        # e.g., debit_account_id != credit_account_id
        # Uses a ternary expression that guarantees inequality while staying
        # within the valid FK range (assumes sequential IDs starting from 1):
        #   value=1 → 2 (boundary: use +1)
        #   value>1 → value-1 (always different, always in [1, value-1] ⊂ [1, N])
        # This is safe for any N >= 2 and avoids the batch-level CHECK failure
        # that would occur with independent random FK selection (~3.3%
        # collision rate per row, ~97% batch failure rate for batches of 100).
        m = re.match(rf"^\s*{col}\s*!=\s*(\w+)\s*$", expr, re.IGNORECASE)
        if m:
            other_col = m.group(1)
            if other_col in col_set and other_col != col_name and is_int_type:
                return {
                    "derive_from": other_col,
                    "expression": "value - 1 if value > 1 else value + 1",
                }

        # Pattern 18: col != VALUE OR other_col = VALUE2 (conditional equality)
        # e.g., is_completed != 1 OR watched_percent = 100
        # Semantics: if col = VALUE, then other_col must = VALUE2.
        # Solution: derive col from other_col — set col = VALUE when
        # other_col = VALUE2, else set col to the opposite (1-VALUE for
        # boolean, 0 for non-boolean). This always satisfies the constraint:
        #   other_col = VALUE2 → col = VALUE → (VALUE != VALUE) OR (VALUE2 = VALUE2) → True
        #   other_col != VALUE2 → col = 1-VALUE → (1-VALUE != VALUE) OR (...) → True
        # Also handles the commutative form: other_col = VALUE2 OR col != VALUE
        p18_other: str | None = None
        p18_val: int = 0
        p18_val2: int = 0
        m18 = re.match(
            rf"^\s*{col}\s*!=\s*(\d+)\s+OR\s+(\w+)\s*=\s*(\d+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m18:
            p18_val = int(m18.group(1))
            p18_other = m18.group(2)
            p18_val2 = int(m18.group(3))
        else:
            # Try commutative form: other_col = VALUE2 OR col != VALUE
            m18 = re.match(
                rf"^\s*(\w+)\s*=\s*(\d+)\s+OR\s+{col}\s*!=\s*(\d+)\s*$",
                expr,
                re.IGNORECASE,
            )
            if m18:
                p18_other = m18.group(1)
                p18_val2 = int(m18.group(2))
                p18_val = int(m18.group(3))
        if m18 and p18_other and p18_other in col_set and p18_other != col_name:
            # For boolean columns (val in {0,1}): opposite is 1-val.
            # For other integer columns: opposite is 0 (safe default).
            opposite = 1 - p18_val if p18_val in (0, 1) else 0
            return {
                "derive_from": p18_other,
                "expression": f"{p18_val} if value == {p18_val2} else {opposite}",
            }

        # Pattern 7: col >= col1 * col2 (arithmetic comparison)
        # e.g., total_price >= unit_price * quantity
        # Derive from the first multiplicand, reference the second via the
        # row dict (ExpressionEngine supports row['col_name'] access).
        # The expression computes exactly col1 * col2, satisfying >= (equality).
        m = re.match(
            rf"^\s*{col}\s*>=\s*(\w+)\s*\*\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1, col2 = m.group(1), m.group(2)
            if col1 in col_set and col2 in col_set and col1 != col_name:
                return {
                    "derive_from": col1,
                    "expression": f"value * row['{col2}']",
                }

        # Pattern 10: col = col1 + col2 (arithmetic equality — sum of two columns)
        # e.g., payment_amount = principal_portion + interest_portion
        # Derive from col1, reference col2 via the row dict. The expression
        # computes exactly col1 + col2, satisfying the equality constraint.
        # Supports +, -, and * operators (division excluded to avoid
        # zero-division errors).
        m = re.match(
            rf"^\s*{col}\s*=\s*(\w+)\s*([+\-*])\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1, op, col2 = m.group(1), m.group(2), m.group(3)
            if col1 in col_set and col2 in col_set and col1 != col_name:
                return {
                    "derive_from": col1,
                    "expression": f"value {op} row['{col2}']",
                }

        # Pattern 11: col = col1 + col2 + col3 (three-column addition equality)
        # e.g., total_amount = consultation_fee + medication_fee + test_fee
        # Derive from col1 (first operand), reference col2 and col3 via row dict.
        # The expression computes exactly col1 + col2 + col3, satisfying the
        # equality constraint. Only supports + operator (most common case for
        # three-column sums like bills, invoices, totals).
        m = re.match(
            rf"^\s*{col}\s*=\s*(\w+)\s*\+\s*(\w+)\s*\+\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1, col2, col3 = m.group(1), m.group(2), m.group(3)
            if col1 in col_set and col2 in col_set and col3 in col_set and col1 != col_name:
                return {
                    "derive_from": col1,
                    "expression": f"value + row['{col2}'] + row['{col3}']",
                }

        # Pattern 19: col1 + col2 = col (reverse sum equality — derive one addend from total)
        # e.g., insurance_covered + self_paid = total_amount
        # When current column is one of the addends (col1 or col2), derive it
        # from the total (col): col = total - other_addend.
        # Supports both orderings: "col + col1 = col2" and "col1 + col = col2".
        # Also supports subtraction: "col1 - col = col2" → col = col1 - col2.
        m = re.match(
            rf"^\s*(\w+)\s*([+\-])\s*{col}\s*=\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if not m:
            # Try reverse ordering: col + col1 = col2
            m = re.match(
                rf"^\s*{col}\s*([+\-])\s*(\w+)\s*=\s*(\w+)\s*$",
                expr,
                re.IGNORECASE,
            )
        if m:
            other_col, op, total_col = m.group(1), m.group(2), m.group(3)
            if other_col in col_set and total_col in col_set and total_col != col_name:
                # col1 + col = col2 → col = col2 - col1
                # col1 - col = col2 → col = col1 - col2
                # col + col1 = col2 → col = col2 - col1
                # col - col1 = col2 → col = col2 + col1
                if op == "+":
                    return {
                        "derive_from": total_col,
                        "expression": f"value - row['{other_col}']",
                    }
                # op == "-"
                return {
                    "derive_from": total_col,
                    "expression": f"row['{other_col}'] - value",
                }

        # Pattern 20: col = VALUE OR other_col < col2 OR other_col > col3 (range membership)
        # e.g., is_abnormal = 0 OR test_value < ref_lower OR test_value > ref_upper
        # Semantics: if col = VALUE, other_col must be in [col2, col3].
        # Solution: derive col from other_col — set col = VALUE when other_col
        # is in range, else set col to opposite (1-VALUE for boolean).
        # Expression: VALUE if (value >= row['col2'] and value <= row['col3']) else (1-VALUE)
        # This satisfies both:
        #   CHECK1: col = VALUE OR other_col < col2 OR other_col > col3
        #   CHECK2: col = (1-VALUE) OR (other_col >= col2 AND other_col <= col3)
        m = re.match(
            rf"^\s*{col}\s*=\s*(\d+)\s+OR\s+(\w+)\s*<\s*(\w+)\s+OR\s+\2\s*>\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            val_str, other_col, col2, col3 = m.group(1), m.group(2), m.group(3), m.group(4)
            if other_col in col_set and col2 in col_set and col3 in col_set and other_col != col_name:
                val = int(val_str)
                opposite = 1 - val if val in (0, 1) else 0
                return {
                    "derive_from": other_col,
                    "expression": (f"{val} if (value >= row['{col2}'] and value <= row['{col3}']) else {opposite}"),
                }

        # Pattern 21: col = (col1 + col2 + col3) / N (average of N columns)
        # e.g., overall_score = (structural_score + electrical_score + plumbing_score) / 3
        # Derive from col1 (first addend), reference col2 + col3 via row dict.
        # The expression computes (value + row[col2] + row[col3]) / N, which
        # satisfies the equality. N must be a positive integer.
        # Also handles 2-column average: col = (col1 + col2) / 2
        # IMPORTANT: for INTEGER columns, SQLite uses integer division in
        # the CHECK constraint, but Python's ``/`` is float division.
        # Without ``int()`` wrapping, a non-divisible sum (e.g., 226/3=75.33)
        # would fail the CHECK (75.33 != 75) because SQLite evaluates CHECK
        # BEFORE applying column affinity. Wrap in ``int()`` to match
        # SQLite's integer division semantics.
        m = re.match(
            rf"^\s*{col}\s*=\s*\(\s*(\w+)\s*\+\s*(\w+)\s*(?:\+\s*(\w+)\s*)?\)\s*/\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1, col2, col3_opt, n_str = m.group(1), m.group(2), m.group(3), m.group(4)
            if col1 in col_set and col2 in col_set and col1 != col_name:
                n_val: float | int = float(n_str) if "." in n_str else int(n_str)
                # Wrap in int() for INTEGER columns to match SQLite's
                # integer division semantics in CHECK constraints.
                int_wrap = "int" if is_int_type else ""
                if col3_opt and col3_opt in col_set:
                    # Three-column average: (value + row[col2] + row[col3]) / N
                    inner = f"(value + row['{col2}'] + row['{col3_opt}']) / {n_val}"
                    return {
                        "derive_from": col1,
                        "expression": f"{int_wrap}({inner})" if int_wrap else inner,
                    }
                # Two-column average: (value + row[col2]) / N
                inner = f"(value + row['{col2}']) / {n_val}"
                return {
                    "derive_from": col1,
                    "expression": f"{int_wrap}({inner})" if int_wrap else inner,
                }

        # Pattern 22: col <= col2 * CONSTANT (percentage/scalar upper bound)
        # e.g., monthly_payment <= monthly_income * 0.5
        # e.g., discount_amount <= total_price * 0.3
        # Derive from col2, multiply by a random factor in [0, CONSTANT] to
        # guarantee col <= col2 * CONSTANT.
        m = re.match(
            rf"^\s*{col}\s*<=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col, c_str = m.group(1), m.group(2)
            if other_col in col_set and other_col != col_name:
                c_val = float(c_str)
                # Generate a random factor in [0, c_val] so the derived
                # value is always <= other_col * c_val. Using 0 as the
                # lower bound allows zero (valid for <= constraints).
                return {
                    "derive_from": other_col,
                    "expression": f"value * random_float(0.0, {c_val})",
                }

        # Pattern 23: col = VALUE OR col1 < X OR col2 < X OR col3 < X
        # (multi-column threshold — derive col as indicator of any column < X)
        # e.g., has_issues = 0 OR structural_score < 60 OR electrical_score < 60 OR plumbing_score < 60
        #
        # Semantics: the OR-chain ``col1 < X OR col2 < X OR ...`` is the
        # "escape" clause; ``col = VALUE`` is the "always-pass" case. The
        # CHECK fails ONLY when col != VALUE AND all columns >= X. Therefore:
        #   - When ANY column < X: col can be either VALUE or (1-VALUE); we
        #     choose (1-VALUE) because in the common dual-CHECK pattern
        #     (CHECK1: col = (1-VALUE) OR (all >= X)) the value is FORCED to
        #     (1-VALUE) here. Choosing (1-VALUE) satisfies BOTH CHECKs.
        #   - When ALL columns >= X: col MUST be VALUE (the only way CHECK2
        #     passes), and CHECK1 also passes (all >= X is true).
        #
        # Dual pattern (for reference, not matched here):
        #   CHECK1: col = (1-VALUE) OR (col1 >= X AND col2 >= X AND col3 >= X)
        # When both CHECKs are present, they together FORCE col to be:
        #   (1-VALUE) if (any < X) else VALUE
        # which is exactly what we produce below.
        #
        # Derive from col1 (first threshold column), reference others via row[...].
        # Also handles 2-column variant: col = VALUE OR col1 < X OR col2 < X
        m = re.match(
            rf"^\s*{col}\s*=\s*(\d+)\s+OR\s+(\w+)\s*<\s*(\d+)\s+OR\s+(\w+)\s*<\s*\3\s*(?:OR\s+(\w+)\s*<\s*\3)?\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            val_str, col1, x_str, col2, col3_opt = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4),
                m.group(5),
            )
            if col1 in col_set and col2 in col_set and col1 != col_name:
                val = int(val_str)
                opposite = 1 - val if val in (0, 1) else 0
                x_val_p23: int = int(x_str)
                if col3_opt and col3_opt in col_set:
                    # Three-column threshold. ``value`` refers to col1 (the
                    # derive_from source). All three columns must be checked
                    # against X — omitting ``value < {x_val}`` would silently
                    # ignore col1's threshold, producing rows that violate the
                    # CHECK when only col1 is below X.
                    cond = f"value < {x_val_p23} or row['{col2}'] < {x_val_p23} or row['{col3_opt}'] < {x_val_p23}"
                    return {
                        "derive_from": col1,
                        "expression": f"{opposite} if ({cond}) else {val}",
                    }
                # Two-column threshold
                return {
                    "derive_from": col1,
                    "expression": f"{opposite} if (value < {x_val_p23} or row['{col2}'] < {x_val_p23}) else {val}",
                }

        # Pattern 24: col = VALUE OR col (>|>=|<|<=) other_col
        # (conditional comparison — col can be a fixed VALUE, or must satisfy
        # a comparison against another column)
        # e.g., base_price_first = 0.0 OR base_price_first > base_price_business
        # Semantics: col = VALUE is always allowed; col != VALUE is allowed
        # only when the comparison holds. We derive col from other_col:
        # 50% chance of VALUE, 50% chance of a value satisfying the comparison.
        m = re.match(
            rf"^\s*{col}\s*=\s*(-?\d+(?:\.\d+)?)\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            val_str, op, other_col = m.group(1), m.group(2), m.group(3)
            if other_col in col_set and other_col != col_name:
                is_float_p24 = "." in val_str
                val_num_p24: float | int = float(val_str) if is_float_p24 else int(val_str)
                # Build expression that produces VALUE or a compliant value
                if op == ">":
                    comp_expr = "value * random_float(1.01, 2.0)" if is_float_p24 else "value + random_int(1, 100)"
                elif op == ">=":
                    comp_expr = "value * random_float(1.0, 2.0)" if is_float_p24 else "value + random_int(0, 100)"
                elif op == "<":
                    comp_expr = "value * random_float(0.5, 0.99)" if is_float_p24 else "value - random_int(1, 100)"
                else:  # <=
                    comp_expr = "value * random_float(0.5, 1.0)" if is_float_p24 else "value - random_int(0, 100)"
                return {
                    "derive_from": other_col,
                    "expression": f"{val_num_p24} if random_int(0, 1) == 0 else {comp_expr}",
                }

        # Pattern 25: col = col1 * col2 + col3 (multiplication + addition chain)
        # e.g., total_amount = unit_price * seat_count + tax_amount
        # Derive from col1 (first operand), reference col2 and col3 via row dict.
        # Also handles col = col1 * col2 - col3 (subtraction variant).
        m = re.match(
            rf"^\s*{col}\s*=\s*(\w+)\s*\*\s*(\w+)\s*([+\-])\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1, col2, sign, col3 = m.group(1), m.group(2), m.group(3), m.group(4)
            if col1 in col_set and col2 in col_set and col3 in col_set and col1 != col_name:
                return {
                    "derive_from": col1,
                    "expression": f"value * row['{col2}'] {sign} row['{col3}']",
                }

        # Pattern 26: col = VALUE OR other_col IN ('a', 'b', 'c')
        # (conditional enum — col = VALUE is always allowed; col != VALUE
        # is allowed only when other_col is in the enum set)
        # e.g., is_lead = 0 OR role IN ('captain', 'first_officer')
        # e.g., refund_amount = 0.0 OR booking_status IN ('cancelled', 'refunded')
        # Derive from other_col: set col to (1-VALUE) when other_col is in
        # the set, else VALUE. This satisfies the CHECK because:
        #   - When other_col IN set: col can be anything (CHECK passes)
        #   - When other_col NOT IN set: col must be VALUE (CHECK passes)
        m = re.match(
            rf"^\s*{col}\s*=\s*(-?\d+(?:\.\d+)?)\s+OR\s+(\w+)\s+IN\s*\(([^)]+)\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            val_str, other_col, values_str = m.group(1), m.group(2), m.group(3)
            if other_col in col_set and other_col != col_name:
                # Parse the values: 'a', 'b', 'c' → ['a', 'b', 'c']
                values = re.findall(r"'([^']*)'", values_str)
                if not values:
                    values = re.findall(r'"([^"]*)"', values_str)
                if values:
                    is_float_p26 = "." in val_str
                    val_num_p26: float | int = float(val_str) if is_float_p26 else int(val_str)
                    # Build Python list literal: ['captain', 'first_officer']
                    py_list = "[" + ", ".join(f"'{v}'" for v in values) + "]"
                    # For int/boolean columns, use (1-VALUE); for float,
                    # use a random positive amount when allowed.
                    if is_float_p26:
                        non_val_expr = "random_float(0.01, 100.0)"
                    else:
                        non_val_expr = str(1 - val_num_p26) if val_num_p26 in (0, 1) else "0"
                    return {
                        "derive_from": other_col,
                        "expression": f"{non_val_expr} if value in {py_list} else {val_num_p26}",
                    }

        # Pattern 36: N-way conditional range with dual bounds (both lower AND upper per clause)
        #   (other_col = 'V1' AND col >= X1 AND col (<|<=) Y1) OR
        #   (other_col = 'V2' AND col >= X2 AND col (<|<=) Y2) OR [...]
        # Each clause constrains col to a specific range [X, Y) or [X, Y]
        # based on other_col's value. Derive col from other_col and emit a
        # nested ternary that picks the appropriate random range per enum.
        # e.g., (risk_category = 'low' AND risk_score >= 1 AND risk_score < 25) OR
        #       (risk_category = 'medium' AND risk_score >= 25 AND risk_score < 50) OR
        #       (risk_category = 'high' AND risk_score >= 50 AND risk_score < 75) OR
        #       (risk_category = 'critical' AND risk_score >= 75 AND risk_score <= 100)
        # For integers: ``random_int(X, Y-1)`` for ``< Y``, ``random_int(X, Y)`` for ``<= Y``.
        # For floats: ``random_float(X, Y-0.01)`` for ``< Y``, ``random_float(X, Y)`` for ``<= Y``.
        # Handles newlines/multi-whitespace in CHECK expressions by normalizing
        # before the guard check (SQLite stores table-level CHECKs with newlines).
        expr_norm = re.sub(r"\s+", " ", expr).strip()
        if " OR " in expr_norm and " AND " in expr_norm:
            clause_re_36 = (
                rf"\(?\s*(\w+)\s*=\s*'([^']+)'\s+AND\s+{col}\s*"
                r"(>=|>)\s*(-?[0-9]+(?:\.[0-9]+)?)\s+AND\s+"
                rf"{col}\s*(<=|<)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*\)?"
            )
            clauses_36 = re.findall(clause_re_36, expr)
            if len(clauses_36) >= 2:
                other_col_p36 = clauses_36[0][0]
                if (
                    other_col_p36 in col_set
                    and other_col_p36 != col_name
                    and all(cl[0] == other_col_p36 for cl in clauses_36)
                ):
                    parts_p36: list[str] = []
                    for _oc, vi, lo_op, lo_str, up_op, up_str in clauses_36[:-1]:
                        lo = float(lo_str)
                        up = float(up_str)
                        # Adjust for exclusive bounds
                        if lo_op == ">":
                            lo += 0.01 if is_float_type else 1
                        if up_op == "<":
                            up -= 0.01 if is_float_type else 1
                        rand_e = (
                            f"random_float({lo}, {up})"
                            if is_float_type
                            else f"random_int({int(lo)}, {int(up)})"
                        )
                        parts_p36.append(f"{rand_e} if value == '{vi}'")
                    # Last clause is the fallback
                    _oc, _vi, lo_op, lo_str, up_op, up_str = clauses_36[-1]
                    lo = float(lo_str)
                    up = float(up_str)
                    if lo_op == ">":
                        lo += 0.01 if is_float_type else 1
                    if up_op == "<":
                        up -= 0.01 if is_float_type else 1
                    last_rand_36 = (
                        f"random_float({lo}, {up})"
                        if is_float_type
                        else f"random_int({int(lo)}, {int(up)})"
                    )
                    expr_chain_36 = last_rand_36
                    for idx in range(len(parts_p36) - 1, -1, -1):
                        expr_chain_36 = f"{parts_p36[idx]} else ({expr_chain_36})"
                    return {
                        "derive_from": other_col_p36,
                        "expression": expr_chain_36,
                    }

        # Pattern 27: N-way conditional range (single bound per clause)
        #   other_col = 'V1' AND col OP1 X1 OR other_col = 'V2' AND col OP2 X2 [OR ...]
        # where OPi ∈ {<=, <, >=, >} and each clause constrains col based on
        # other_col's value. Derive col from other_col and emit a nested
        # ternary that picks the appropriate random range for each enum value.
        # e.g., bag_type = 'carry_on' AND weight_kg <= 10.0
        #       OR bag_type = 'checked' AND weight_kg <= 32.0
        #       OR bag_type = 'oversized' AND weight_kg > 32.0
        # This pattern handles 2-4 clauses. Clauses with ``<= X`` produce
        # ``random_float(0.01, X)``; ``>= X`` produces ``random_float(X, X+100)``;
        # ``> X`` produces ``random_float(X+0.01, X+100)`` (epsilon for strict
        # inequality); ``< X`` produces ``random_float(0.01, X-0.01)``.
        # Uses ``expr_norm`` (whitespace-normalized) for the guard check to
        # handle SQLite table-level CHECKs stored with newlines.
        if " OR " in expr_norm and " AND " in expr_norm:
            clause_re = (
                rf"(\w+)\s*=\s*'([^']+)'\s+AND\s+{col}\s*"
                r"(>=|<=|>|<)\s*(-?[0-9]+(?:\.[0-9]+)?)"
            )
            clauses = re.findall(clause_re, expr)
            # Require at least 2 clauses AND that the whole expr is exactly
            # the OR-chain (no extra terms). Each clause: (other_col, Vi, OPi, Xi).
            if len(clauses) >= 2:
                # Verify all clauses reference the SAME other column
                other_col_p27 = clauses[0][0]
                if (
                    other_col_p27 in col_set
                    and other_col_p27 != col_name
                    and all(cl[0] == other_col_p27 for cl in clauses)
                ):
                    # Build nested ternary: ``rand_a if value=='V1' else (rand_b if value=='V2' else rand_c)``
                    # Last clause is the fallback.
                    parts_p27: list[str] = []
                    for _other, vi, opi, xi in clauses[:-1]:
                        xi_num = float(xi)
                        rand_expr = _range_expr_for_op(opi, xi_num)
                        parts_p27.append(f"{rand_expr} if value == '{vi}'")
                    _other, _last_vi, last_op, last_xi = clauses[-1]
                    last_rand = _range_expr_for_op(last_op, float(last_xi))
                    # Chain with ``else (next)`` and final ``else <fallback>``
                    expr_chain = last_rand
                    for idx in range(len(parts_p27) - 1, -1, -1):
                        expr_chain = f"{parts_p27[idx]} else ({expr_chain})"
                    return {
                        "derive_from": other_col_p27,
                        "expression": expr_chain,
                    }

        # Pattern 37: multiple ``col1 != VALUE_i OR col OP_i X_i`` on same column
        # (multi-conditional cross-column — when 2+ separate CHECK constraints
        # constrain the SAME target column based on the SAME enum column's value)
        # e.g.:
        #   CHECK (movement_type != 'inbound' OR quantity > 0)
        #   CHECK (movement_type != 'outbound' OR quantity < 0)
        #   CHECK (movement_type != 'adjustment' OR quantity != 0)
        # Each constraint means: "when col1 == VALUE_i, col must satisfy OP_i X_i".
        # Derive col from col1 and emit a nested ternary with a branch per VALUE.
        # Branches:
        #   ``> X``  → random_int(X+1, X+100) or random_float(X+0.01, X+100.0)
        #   ``>= X`` → random_int(X, X+100) or random_float(X, X+100.0)
        #   ``< X``  → random_int(X-100, X-1) or random_float(X-100.0, X-0.01)
        #   ``<= X`` → random_int(X-100, X) or random_float(X-100.0, X)
        #   ``!= X`` → random non-X value (pick from positive or negative range)
        # Default branch (col1 not in any VALUE set): random_int(-100, 100).
        # This pattern MUST run before Pattern 28 (single-condition case) so
        # the multi-branch expression wins when 2+ conditions exist.
        p37_branches: list[tuple[str, str, float, bool]] = []
        p37_other_col: str | None = None
        for c_p37 in constraints:
            if c_p37.get("type") != "check":
                continue
            expr_p37 = c_p37.get("expression", "")
            if not expr_p37:
                continue
            m_p37 = re.match(
                rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*(>=|<=|>|<|!=)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*$",
                expr_p37,
                re.IGNORECASE,
            )
            if not m_p37:
                continue
            other_p37, val_p37, op_p37, x_str_p37 = (
                m_p37.group(1),
                m_p37.group(2),
                m_p37.group(3),
                m_p37.group(4),
            )
            # All branches must reference the same enum column
            if other_p37 not in col_set or other_p37 == col_name:
                continue
            if p37_other_col is None:
                p37_other_col = other_p37
            elif p37_other_col != other_p37:
                continue
            x_val_p37 = float(x_str_p37)
            is_float_p37 = "." in x_str_p37
            p37_branches.append((val_p37, op_p37, x_val_p37, is_float_p37))
        if p37_other_col is not None and len(p37_branches) >= 2:
            # Build nested ternary: branch1 if value == 'V1' else (branch2 if value == 'V2' else ... else default)
            use_float = any(b[3] for b in p37_branches)
            parts_p37: list[str] = []
            for val_p37, op_p37, x_p37, _ in p37_branches:
                if use_float:
                    if op_p37 == ">":
                        branch = f"random_float({x_p37 + 0.01}, {x_p37 + 100.0})"
                    elif op_p37 == ">=":
                        branch = f"random_float({x_p37}, {x_p37 + 100.0})"
                    elif op_p37 == "<":
                        branch = f"random_float({x_p37 - 100.0}, {x_p37 - 0.01})"
                    elif op_p37 == "<=":
                        branch = f"random_float({x_p37 - 100.0}, {x_p37})"
                    else:  # !=
                        # Non-X value: alternate positive and negative ranges
                        pos = f"random_float({x_p37 + 0.01}, {x_p37 + 100.0})"
                        neg = f"random_float({x_p37 - 100.0}, {x_p37 - 0.01})"
                        branch = f"({pos} if random_int(0, 1) == 0 else {neg})"
                else:
                    x_int_p37 = int(x_p37)
                    if op_p37 == ">":
                        branch = f"random_int({x_int_p37 + 1}, {x_int_p37 + 100})"
                    elif op_p37 == ">=":
                        branch = f"random_int({x_int_p37}, {x_int_p37 + 100})"
                    elif op_p37 == "<":
                        branch = f"random_int({x_int_p37 - 100}, {x_int_p37 - 1})"
                    elif op_p37 == "<=":
                        branch = f"random_int({x_int_p37 - 100}, {x_int_p37})"
                    else:  # !=
                        # Non-X value: alternate positive and negative ranges
                        pos = f"random_int({x_int_p37 + 1}, {x_int_p37 + 100})"
                        neg = f"random_int({x_int_p37 - 100}, {x_int_p37 - 1})"
                        branch = f"({pos} if random_int(0, 1) == 0 else {neg})"
                parts_p37.append(f"{branch} if value == '{val_p37}'")
            # Default branch: covers enum values not in any VALUE set
            default_p37 = "random_float(-100.0, 100.0)" if use_float else "random_int(-100, 100)"
            # Build nested ternary: a if cond1 else (b if cond2 else (... else default))
            expr_p37_final = default_p37
            for cond_p37 in reversed(parts_p37):
                expr_p37_final = f"{cond_p37} else ({expr_p37_final})"
            return {
                "derive_from": p37_other_col,
                "expression": expr_p37_final,
            }

        # Pattern 28: col1 != VALUE OR col2 > 0
        # (conditional requirement — when col1 == VALUE, col2 must be > 0;
        # otherwise col2 can be anything, including 0)
        # e.g., bag_type != 'oversized' OR fee_amount > 0.0
        # e.g., status != 'approved' OR approved_amount > 0.0
        # Derive from col1: when col1 == VALUE, set col2 to a positive random
        # value; otherwise set col2 to 0 (or empty for strings).
        #
        # Cross-column upper bound awareness: if another CHECK constrains
        # ``col <= other_upper_col`` (or ``col < other_upper_col``), the
        # hardcoded upper bound (threshold + 100.0) may exceed
        # other_upper_col, causing CHECK violations at fill time. When such
        # a constraint exists, cap the positive expression with
        # ``min(random_float(...), row['other_upper_col'])`` to guarantee
        # the upper bound is respected. The ``min`` function is in
        # SAFE_FUNCTIONS (see core/expression.py).
        m = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*>\s*(-?[0-9]+(?:\.[0-9]+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p28, val_str_p28, threshold_str = m.group(1), m.group(2), m.group(3)
            if other_col_p28 in col_set and other_col_p28 != col_name:
                threshold = float(threshold_str)
                # When col1 == VALUE: col2 must be > threshold. Use
                # threshold+0.01 as the lower bound (epsilon for strict >).
                positive_expr = f"random_float({threshold + 0.01}, {threshold + 100.0})"
                # Check for other CHECKs that constrain col <= other_col
                # or col < other_col (cross-column upper bound). If found,
                # cap the positive expression to respect the upper bound.
                for other_c_p28 in constraints:
                    if other_c_p28 is c:
                        continue
                    if other_c_p28.get("type") != "check":
                        continue
                    other_expr_p28 = other_c_p28.get("expression", "")
                    m_upper_p28 = re.search(
                        rf"{col}\s*(<=|<)\s*(\w+)",
                        other_expr_p28,
                        re.IGNORECASE,
                    )
                    if m_upper_p28:
                        upper_col_p28 = m_upper_p28.group(2)
                        if upper_col_p28 in col_set and upper_col_p28 != col_name:
                            positive_expr = (
                                f"min({positive_expr}, row['{upper_col_p28}'])"
                            )
                            break
                # When col1 != VALUE: col2 can be 0 (or any value >= 0).
                zero_expr = "0.0"
                return {
                    "derive_from": other_col_p28,
                    "expression": f"{positive_expr} if value == '{val_str_p28}' else {zero_expr}",
                }

        # Pattern 12: col = abs(col1) (*|+|-) col2 (abs() wrapper on first operand)
        # e.g., total_value = abs(quantity) * price_per_unit
        # Derive from col1 (the column inside abs()), reference col2 via row dict.
        # The expression computes abs(col1) {op} col2, satisfying the equality.
        # ``abs`` is in SAFE_FUNCTIONS (see core/expression.py line 53).
        # Supports +, -, * operators (division excluded to avoid zero-division).
        m = re.match(
            rf"^\s*{col}\s*=\s*abs\s*\(\s*(\w+)\s*\)\s*([+\-*])\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1, op, col2 = m.group(1), m.group(2), m.group(3)
            if col1 in col_set and col2 in col_set and col1 != col_name:
                return {
                    "derive_from": col1,
                    "expression": f"abs(value) {op} row['{col2}']",
                }

        # Pattern 13: col = col1 (*|+|-) abs(col2) (abs() wrapper on second operand)
        # e.g., net_value = price_per_unit * abs(quantity)
        # Derive from col1, apply abs() to the row-referenced second operand.
        m = re.match(
            rf"^\s*{col}\s*=\s*(\w+)\s*([+\-*])\s*abs\s*\(\s*(\w+)\s*\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1, op, col2 = m.group(1), m.group(2), m.group(3)
            if col1 in col_set and col2 in col_set and col1 != col_name:
                return {
                    "derive_from": col1,
                    "expression": f"value {op} abs(row['{col2}'])",
                }

        # Pattern 14: col = abs(col1) * abs(col2) (abs() wrappers on both operands)
        # e.g., total = abs(delta_a) * abs(delta_b)
        # Derive from col1, apply abs() to both operands.
        m = re.match(
            rf"^\s*{col}\s*=\s*abs\s*\(\s*(\w+)\s*\)\s*\*\s*abs\s*\(\s*(\w+)\s*\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1, col2 = m.group(1), m.group(2)
            if col1 in col_set and col2 in col_set and col1 != col_name:
                return {
                    "derive_from": col1,
                    "expression": f"abs(value) * abs(row['{col2}'])",
                }

        # Pattern 15: col = abs(col1) (standalone abs — magnitude)
        # e.g., magnitude = abs(delta)
        # Derive from col1, apply abs() to value.
        m = re.match(
            rf"^\s*{col}\s*=\s*abs\s*\(\s*(\w+)\s*\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1 = m.group(1)
            if col1 in col_set and col1 != col_name:
                return {
                    "derive_from": col1,
                    "expression": "abs(value)",
                }

        # Pattern 29: col = col1 (+|-) col2 (+|-) col3 (three-column arithmetic
        # chain with mixed + and - operators)
        # e.g., available = balance + credit_limit - held
        # e.g., net_amount = gross_amount - discount + tax
        # Derive from col1 (first operand), reference col2 and col3 via row dict.
        # The expression computes value {op1} row[col2] {op2} row[col3],
        # satisfying the equality.
        m = re.match(
            rf"^\s*{col}\s*=\s*(\w+)\s*([+\-])\s*(\w+)\s*([+\-])\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1, op1, col2, op2, col3 = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            if col1 in col_set and col2 in col_set and col3 in col_set and col1 != col_name:
                return {
                    "derive_from": col1,
                    "expression": f"value {op1} row['{col2}'] {op2} row['{col3}']",
                }

        # Pattern 30: col1 != VALUE OR col IS NULL (conditional NULL — when
        # col1 == VALUE, col must be NULL; otherwise col can be anything)
        # e.g., position != 'ceo' OR manager_id IS NULL
        # e.g., status != 'closed' OR closed_at IS NULL
        # Derive from col1: when col1 == VALUE, set col to None; otherwise
        # set col to a safe value. For FK columns (integer), returning None
        # is the safest approach — it avoids FK violations while satisfying
        # the CHECK. For non-FK columns, None is also valid (SQLite allows
        # NULL unless NOT NULL is specified).
        # NOTE: the ``None`` literal is supported by the expression engine
        # (simpleeval evaluates Python None). The orchestrator's derive_from
        # handler accepts None as a valid value (stored as NULL in the DB).
        # ADVERSARIAL FIX: for FK columns, the non-null branch previously
        # returned ``0`` (for int) — but ``0`` is NEVER a valid FK value
        # (auto-increment IDs start from 1). This caused FK violations at
        # fill time. Now, FK columns return ``None`` for BOTH branches,
        # making the column always NULL. This is semantically acceptable
        # because FK columns in Pattern 30 are nullable (the CHECK requires
        # IS NULL for some values, so the column must be nullable).
        m = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s+IS\s+NULL\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p30, val_str_p30 = m.group(1), m.group(2)
            if other_col_p30 in col_set and other_col_p30 != col_name:
                # When col1 == VALUE: col = None (NULL)
                # When col1 != VALUE: col = a safe default (0 for int, 0.0 for float)
                # For FK columns: always None (0 is never a valid FK id)
                null_expr = "None"
                non_null_expr = "None" if is_fk_column else ("0.0" if is_float_type else "0")
                return {
                    "derive_from": other_col_p30,
                    "expression": f"{null_expr} if value == '{val_str_p30}' else {non_null_expr}",
                }

        # Pattern 31: col1 != VALUE OR col = VALUE2 (conditional equality —
        # when col1 == VALUE, col must be exactly VALUE2; otherwise col can
        # be anything)
        # e.g., status != 'paid_off' OR remaining = 0.0
        # e.g., type != 'completed' OR fee = 0.0
        # Derive from col1: when col1 == VALUE, set col to VALUE2; otherwise
        # set col to a safe random value. The ``else`` branch uses a small
        # positive range to avoid violating other CHECKs (e.g., remaining
        # must be <= principal). For integer VALUE2, use int; for float, use float.
        m = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*=\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p31, val_str_p31, eq_val_str = m.group(1), m.group(2), m.group(3)
            if other_col_p31 in col_set and other_col_p31 != col_name:
                is_float_p31 = "." in eq_val_str
                eq_val: float | int = float(eq_val_str) if is_float_p31 else int(eq_val_str)
                # When col1 == VALUE: col = VALUE2 (exact)
                # When col1 != VALUE: col = random value in a safe range.
                # Using [0.01, 100.0] for floats and [1, 100] for ints to
                # avoid zero (which might violate ``col > 0`` CHECKs) while
                # staying small enough to not exceed other columns' values.
                rand_expr = "random_float(0.01, 100.0)" if is_float_p31 else "random_int(1, 100)"
                return {
                    "derive_from": other_col_p31,
                    "expression": f"{eq_val} if value == '{val_str_p31}' else {rand_expr}",
                }

        # Pattern 22b: col >= X AND col <= col2 * CONSTANT (compound range
        # with multiplier upper bound)
        # e.g., fee >= 0.0 AND fee <= amount * 0.02
        # e.g., tax >= 0.0 AND tax <= subtotal * 0.08
        # Derive from col2, multiply by a random factor in [0, CONSTANT] to
        # guarantee col <= col2 * CONSTANT. The lower bound X is satisfied
        # by using max(X, ...) in the expression.
        m = re.match(
            rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            x_str_p22b, other_col_p22b, c_str_p22b = m.group(1), m.group(2), m.group(3)
            if other_col_p22b in col_set and other_col_p22b != col_name:
                x_val_p22b = float(x_str_p22b) if "." in x_str_p22b else int(x_str_p22b)
                c_val_p22b = float(c_str_p22b)
                # Generate value * random_factor where random_factor ∈ [0, c_val]
                # This guarantees col <= col2 * c_val. The lower bound X is
                # satisfied because value * 0 = 0 >= X when X <= 0 (common case).
                # For X > 0, use max(X, ...) to enforce the lower bound.
                if x_val_p22b <= 0:
                    return {
                        "derive_from": other_col_p22b,
                        "expression": f"value * random_float(0.0, {c_val_p22b})",
                    }
                # X > 0: need to ensure col >= X. Use max(X, value * factor).
                return {
                    "derive_from": other_col_p22b,
                    "expression": f"max({x_val_p22b}, value * random_float(0.0, {c_val_p22b}))",
                }

        # Pattern 32: (col1 = VALUE AND col > X) OR (col1 IN (...) AND col IS NULL)
        # (conditional value/NULL — col must be > X when col1 == VALUE,
        # and must be NULL when col1 is in the other set)
        # e.g., (card_type = 'credit' AND credit_limit > 0.0)
        #       OR (card_type IN ('debit', 'prepaid') AND credit_limit IS NULL)
        # Derive from col1: when col1 == VALUE, set col to a positive random;
        # when col1 IN other set, set col to None.
        m = re.match(
            rf"^\s*\(\s*(\w+)\s*=\s*'([^']+)'\s+AND\s+{col}\s*>\s*(-?\d+(?:\.\d+)?)\s*\)\s*OR\s*\(\s*\1\s+IN\s*\(([^)]+)\)\s+AND\s+{col}\s+IS\s+NULL\s*\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p32, val_str_p32, threshold_str_p32, values_str_p32 = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4),
            )
            if other_col_p32 in col_set and other_col_p32 != col_name:
                threshold_p32 = float(threshold_str_p32)
                values_p32 = re.findall(r"'([^']*)'", values_str_p32)
                if not values_p32:
                    values_p32 = re.findall(r'"([^"]*)"', values_str_p32)
                if values_p32:
                    py_list_p32 = "[" + ", ".join(f"'{v}'" for v in values_p32) + "]"
                    # When col1 == VALUE: col = random positive (> threshold)
                    # When col1 IN other set: col = None (NULL)
                    positive_expr_p32 = f"random_float({threshold_p32 + 0.01}, {threshold_p32 + 10000.0})"
                    null_branch = f"None if value in {py_list_p32} else {positive_expr_p32}"
                    return {
                        "derive_from": other_col_p32,
                        "expression": f"({positive_expr_p32}) if value == '{val_str_p32}' else ({null_branch})",
                    }

        # Pattern 33: (col1 IN (...) AND col = col2 + col3) OR (col1 IN (...) AND col = col2 - col3)
        # (conditional arithmetic based on type — col is computed differently
        # depending on col1's value)
        # e.g., (type IN ('deposit', 'transfer_in', 'interest') AND balance_after = balance_before + amount)
        #       OR (type IN ('withdrawal', 'transfer_out', 'fee') AND balance_after = balance_before - amount)
        # Derive from col2 (the base value), reference col1 (type) and col3 (amount) via row dict.
        m = re.match(
            rf"^\s*\(\s*(\w+)\s+IN\s*\(([^)]+)\)\s+AND\s+{col}\s*=\s*(\w+)\s*([+\-])\s*(\w+)\s*\)\s*OR\s*\(\s*\1\s+IN\s*\(([^)]+)\)\s+AND\s+{col}\s*=\s*\3\s*([+\-])\s*\5\s*\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            type_col_p33, set1_str, base_col_p33, op1_p33, amt_col_p33, _set2_str, op2_p33 = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4),
                m.group(5),
                m.group(6),
                m.group(7),
            )
            if (
                type_col_p33 in col_set
                and base_col_p33 in col_set
                and amt_col_p33 in col_set
                and base_col_p33 != col_name
            ):
                set1_vals = re.findall(r"'([^']*)'", set1_str)
                if not set1_vals:
                    set1_vals = re.findall(r'"([^"]*)"', set1_str)
                if set1_vals:
                    py_list1_p33 = "[" + ", ".join(f"'{v}'" for v in set1_vals) + "]"
                    # When type IN set1: col = base + amount (op1)
                    # When type IN set2: col = base - amount (op2)
                    expr_p33 = (
                        f"(value {op1_p33} row['{amt_col_p33}']) if row['{type_col_p33}'] in {py_list1_p33} "
                        f"else (value {op2_p33} row['{amt_col_p33}'])"
                    )
                    return {
                        "derive_from": base_col_p33,
                        "expression": expr_p33,
                    }

        # Pattern 34: col1 != VALUE OR col2 < X (conditional upper bound)
        # e.g., status != 'dormant' OR balance < 100.0
        # When col1 != VALUE: col2 must be < X (exclusive upper bound)
        # When col1 == VALUE: col2 can be anything (no upper restriction)
        # Safe approach: set max_value to X - epsilon unconditionally. This is
        # more restrictive than necessary for the VALUE case (dormant accounts
        # could have balance >= 100.0), but satisfies ALL CHECKs. The single-
        # column lower bound (if any) is preserved by calling
        # ``_infer_from_check_constraints`` to recover min_value (e.g.,
        # ``balance >= -10000.0``).
        # Also handles ``col1 != VALUE OR col2 <= X`` (inclusive upper bound).
        m = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*(<|<=)\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p34, _val_str_p34, op_p34, x_str_p34 = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4),
            )
            if other_col_p34 in col_set and other_col_p34 != col_name:
                is_float_p34 = "." in x_str_p34
                x_val_p34 = float(x_str_p34)
                # Get single-column params (e.g., min_value from `balance >= -10000.0`)
                # to preserve the lower bound that would otherwise be lost when
                # cross-column inference overrides single-column inference.
                single_p34 = _infer_from_check_constraints(col_name, constraints, all_columns)
                if op_p34 == "<":
                    # Exclusive: max must be < X, so set max_value = X - epsilon
                    if is_float_p34:
                        params_p34: dict[str, Any] = {"max_value": x_val_p34 - 0.01}
                        gen_p34 = "float"
                    else:
                        params_p34 = {"max_value": int(x_val_p34) - 1}
                        gen_p34 = "integer"
                elif is_float_p34:
                    # Inclusive: max can be = X, so set max_value = X
                    params_p34 = {"max_value": x_val_p34}
                    gen_p34 = "float"
                else:
                    params_p34 = {"max_value": int(x_val_p34)}
                    gen_p34 = "integer"
                # Merge single-column lower bound if available
                if single_p34 and single_p34[1].get("min_value") is not None:
                    params_p34["min_value"] = single_p34[1]["min_value"]
                return {"generator": gen_p34, "params": params_p34}

        # Pattern 35: col1 IN (...) OR col IS NULL (conditional NULL with IN set)
        # e.g., status IN ('completed') OR completed_at IS NULL
        # When col1 IN set: col can be anything
        # When col1 NOT IN set: col must be NULL
        # For date columns: return null_ratio=1.0 (always NULL). This is the
        # safest approach — it satisfies both this CHECK and any
        # ``col IS NULL OR col > other`` CHECK that might also exist. The
        # trade-off is that the column is always NULL (semantically suboptimal
        # but functionally correct). The LLM can improve this later.
        # For non-date columns: derive from col1, return None when NOT in set.
        m = re.match(
            rf"^\s*(\w+)\s+IN\s*\(([^)]+)\)\s+OR\s+{col}\s+IS\s+NULL\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p35, values_str_p35 = m.group(1), m.group(2)
            if other_col_p35 in col_set and other_col_p35 != col_name:
                if is_date_col:
                    # Always NULL — satisfies both Pattern 35 and Pattern 1
                    return {"generator": "datetime", "params": {}, "null_ratio": 1.0}
                # Non-date: derive from col1, None when not in set
                values_p35 = re.findall(r"'([^']*)'", values_str_p35)
                if not values_p35:
                    values_p35 = re.findall(r'"([^"]*)"', values_str_p35)
                if values_p35:
                    py_list_p35 = "[" + ", ".join(f"'{v}'" for v in values_p35) + "]"
                    non_null_expr_p35 = "0.0" if is_float_type else "0"
                    return {
                        "derive_from": other_col_p35,
                        "expression": f"{non_null_expr_p35} if value in {py_list_p35} else None",
                    }

    return None
