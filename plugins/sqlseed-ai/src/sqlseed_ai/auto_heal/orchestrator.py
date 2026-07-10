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
from sqlseed.generators._dispatch import GeneratorDispatchMixin

logger = get_logger(__name__)

# Valid generator names accepted by the orchestrator's safety net. Includes:
# - All 35 generators in ``GeneratorDispatchMixin.GENERATOR_MAP`` (the
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
                if gen is not None and gen not in _VALID_GENERATORS:
                    gen = None
                    c.pop("generator", None)

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
                if (
                    not has_derive
                    and gen is not None
                    and gen != "uuid"
                    and meta is not None
                    and "uuid" in c.get("name", "").lower()
                    and not _has_like_constraint(c.get("name", ""), meta.constraints)
                ):
                    gen = "uuid"
                    c["generator"] = "uuid"
                    c.pop("params", None)
                    params = {}

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
                if not has_derive and gen in ("string", "catch_phrase") and meta is not None:
                    col_name_sd = c.get("name", "").lower()
                    if col_name_sd and not _has_like_constraint(c.get("name", ""), meta.constraints):
                        mapper_sd = _get_column_mapper()
                        semantic_gen = mapper_sd.EXACT_MATCH_RULES.get(col_name_sd)
                        # Only upgrade if the semantic generator is more
                        # specific than the current generic one. Generic
                        # text generators produce random text that doesn't
                        # match the column's semantic intent.
                        _GENERIC_TEXT_GENS = {"string", "catch_phrase", "sentence", "text"}
                        if semantic_gen and semantic_gen not in _GENERIC_TEXT_GENS:
                            c["generator"] = semantic_gen
                            # Apply EXACT_MATCH_PARAMS if available (e.g.,
                            # ``latitude`` has min/max_value from
                            # EXACT_MATCH_PARAMS).
                            semantic_params = mapper_sd.EXACT_MATCH_PARAMS.get(col_name_sd, {})
                            if semantic_params:
                                c["params"] = dict(semantic_params)
                            else:
                                c["params"] = {}
                            gen = semantic_gen
                            params = c["params"]

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
                if not has_derive and gen is not None and meta is not None:
                    col_name_pg = c.get("name", "")
                    if col_name_pg in meta.column_types:
                        col_type_pg = meta.column_types.get(col_name_pg, "")
                        base_type_pg = re.sub(r"\(.*\)", "", col_type_pg.upper()).strip()
                        is_pg_array = base_type_pg.endswith("[]") or base_type_pg == "ARRAY"
                        is_pg_specific = base_type_pg in ("INTERVAL", "TSVECTOR", "TSTZRANGE")
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
                            params = c["params"]

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
                if not has_derive and gen and meta is not None:
                    col_name = c.get("name", "")
                    if col_name in meta.columns:
                        inferred = _infer_from_check_constraints(col_name, meta.constraints, meta.columns)
                        if inferred is not None:
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
                            elif (
                                inf_gen == "choice"
                                and gen == "choice"
                                and inf_params
                                and "choices" in inf_params
                            ):
                                # Case 4: IN-constraint override. Both
                                # generators are ``choice`` but the current
                                # choices (from L3 exact match or LLM) don't
                                # match the IN-constraint values. The IN
                                # constraint is authoritative — override.
                                # Example: L3 gives ``choices: [0, 1]`` but
                                # CHECK says ``status IN ('active', ...)``.
                                c["params"] = inf_params
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
                            col_name, meta.constraints, meta.columns, col_type, fk_cols_set_55,
                            column_types=meta.column_types,
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

        # Pattern 27 source-column choices constraint: when a multi-clause
        # CHECK like ``status = 'active' AND col >= 0 OR status = 'completed'
        # AND col >= 100 OR status = 'dropped' AND col < 100`` exists, the
        # source column (status) can ONLY take values mentioned in the clauses
        # ('active', 'completed', 'dropped'). Any other value (e.g.,
        # 'refunded') causes the CHECK to fail because no clause matches.
        # This safety net scans for Pattern 27 constraints and constrains the
        # source column's choice generator to only include allowed values.
        for tcfg in config.get("tables", []):
            table_name = tcfg.get("name", "")
            meta = snapshot.tables.get(table_name)
            if meta is None:
                continue
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
            table_name_r = tcfg.get("name", "")
            meta_r = snapshot.tables.get(table_name_r)
            if meta_r is None:
                continue
            columns_r = tcfg.get("columns", [])
            col_map_r: dict[str, dict[str, Any]] = {c.get("name", ""): c for c in columns_r}
            # Collect REAL columns with arithmetic derive_from expressions
            real_derived_cols_r: list[dict[str, Any]] = []
            for c_r in columns_r:
                col_name_r = c_r.get("name", "")
                if "derive_from" not in c_r:
                    continue
                if col_name_r not in meta_r.column_types:
                    continue
                col_type_r = meta_r.column_types.get(col_name_r, "")
                base_type_r = re.sub(r"\(.*\)", "", col_type_r.upper()).strip()
                if base_type_r != "REAL":
                    continue
                expr_r = str(c_r.get("expression", ""))
                # Detect arithmetic on value or row[] refs (but not in
                # function names like abs(), random_float())
                if re.search(r"\bvalue\s*[\*\+\-]|[\*\+\-]\s*row\[|[\*\+\-]\s*abs\(", expr_r):
                    real_derived_cols_r.append(c_r)
            # Convert source columns from float to integer
            for derived_col_r in real_derived_cols_r:
                source_cols_r: list[str] = []
                derive_from_r = derived_col_r.get("derive_from", "")
                if derive_from_r:
                    source_cols_r.append(derive_from_r)
                expr_r = derived_col_r.get("expression", "")
                for m_r in re.finditer(r"row\['([^']+)'\]", expr_r):
                    source_cols_r.append(m_r.group(1))
                # Dedupe preserving order
                source_cols_r = list(dict.fromkeys(source_cols_r))
                for src_name_r in source_cols_r:
                    src_col_r = col_map_r.get(src_name_r)
                    if src_col_r is None:
                        continue
                    src_gen_r = src_col_r.get("generator")
                    src_params_r = src_col_r.get("params") or {}
                    # Only convert float generators with precision (fractional values)
                    if src_gen_r == "float" and "precision" in src_params_r:
                        new_min = int(src_params_r.get("min_value", 0))
                        new_max = int(src_params_r.get("max_value", 999))
                        if new_max <= new_min:
                            new_max = new_min + 100
                        # Cap max to ensure products stay within 32-bit exact range
                        # 2^24 = 16777216; sqrt(16777216) ≈ 4096, so cap at 4000 for safety
                        if new_max > 4000:
                            new_max = 4000
                        src_col_r["generator"] = "integer"
                        src_col_r["params"] = {"min_value": new_min, "max_value": new_max}

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
            table_name_c = tcfg.get("name", "")
            meta_c = snapshot.tables.get(table_name_c)
            if meta_c is None:
                continue
            for c_c in tcfg.get("columns", []):
                col_name_c = c_c.get("name", "")
                # Skip already-NULL columns
                if c_c.get("null_ratio", 0) >= 1.0:
                    continue
                # Skip autoincrement and FK columns
                gen_c = c_c.get("generator")
                if gen_c in ("autoincrement", "foreign_key_or_integer"):
                    continue
                if col_name_c not in meta_c.columns:
                    continue
                col_name_upper_c = col_name_c.upper()
                # Skip if ANY CHECK requires this column to be NOT NULL
                # (setting null_ratio=1.0 would violate those CHECKs)
                requires_not_null_c = False
                for constraint_c in meta_c.constraints:
                    if constraint_c.get("type") != "check":
                        continue
                    expr_c_norm = _normalize_pg_check_expr(constraint_c.get("expression", ""))
                    if f"{col_name_upper_c} IS NOT NULL" in expr_c_norm.upper():
                        requires_not_null_c = True
                        break
                if requires_not_null_c:
                    continue
                # Check for complex conditional CHECK (OR + IS NULL + cross-column)
                # that no pattern matched
                has_complex_check_c = False
                for constraint_c in meta_c.constraints:
                    if constraint_c.get("type") != "check":
                        continue
                    expr_c = constraint_c.get("expression", "")
                    if not expr_c:
                        continue
                    expr_c_norm = _normalize_pg_check_expr(expr_c)
                    expr_c_upper = expr_c_norm.upper()
                    if col_name_upper_c not in expr_c_upper:
                        continue
                    # Complex conditional: has OR with IS NULL for this column
                    # AND references other columns
                    if (
                        " OR " in expr_c_upper
                        and f"{col_name_upper_c} IS NULL" in expr_c_upper
                        and _has_cross_column_check(col_name_c, meta_c.constraints)
                    ):
                        has_complex_check_c = True
                        break
                if has_complex_check_c:
                    # Before forcing null_ratio=1.0, check if the pattern
                    # engine (_infer_cross_column_config) can match this
                    # column's CHECK. If it can, the pattern already
                    # handled it (either via LLM-set derive_from or via the
                    # cross-column restoration in the main loop) — don't
                    # override. Only force null_ratio=1.0 when NO pattern
                    # matched (the complex CHECK is truly unhandled).
                    col_type_c = meta_c.column_types.get(col_name_c, "TEXT")
                    fk_cols_set_c: set[str] = set()
                    for fk_c in meta_c.foreign_keys:
                        for fc_c in fk_c.get("columns", []):
                            fk_cols_set_c.add(fc_c)
                    cross_result_c = _infer_cross_column_config(
                        col_name_c, meta_c.constraints, meta_c.columns,
                        col_type_c, fk_cols_set_c,
                        column_types=meta_c.column_types,
                    )
                    if cross_result_c is not None and "derive_from" in cross_result_c:
                        # Pattern matched — skip null_ratio override
                        continue
                    c_c["null_ratio"] = 1.0
                    # Remove generator/params/derive_from since null_ratio=1.0
                    # means all NULL
                    c_c.pop("generator", None)
                    c_c.pop("params", None)
                    c_c.pop("derive_from", None)
                    c_c.pop("expression", None)

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
            table_name_sn7 = tcfg_sn7.get("name", "")
            meta_sn7 = snapshot.tables.get(table_name_sn7)
            if meta_sn7 is None:
                continue
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
            for c_sn7 in tcfg_sn7.get("columns", []):
                if c_sn7.get("null_ratio", 0) < 1.0:
                    continue
                col_name_sn7 = c_sn7.get("name", "")
                if col_name_sn7 not in meta_sn7.columns:
                    continue
                col_name_upper_sn7 = col_name_sn7.upper()
                is_self_ref_fk_sn7 = col_name_sn7 in self_ref_fk_cols_sn7
                # Check if any CHECK constraint requires this column to be
                # NOT NULL (contains ``IS NOT NULL`` for this column).
                requires_not_null_sn7 = False
                for constraint_sn7 in meta_sn7.constraints:
                    if constraint_sn7.get("type") != "check":
                        continue
                    expr_sn7_norm = _normalize_pg_check_expr(constraint_sn7.get("expression", ""))
                    if f"{col_name_upper_sn7} IS NOT NULL" in expr_sn7_norm.upper():
                        requires_not_null_sn7 = True
                        break
                # Check if any non-null_ratio column derives from this column
                # (case b). If a dependent column has no null_ratio and
                # derives_from this null_ratio=1.0 column, the dependent will
                # likely produce NULL values when the source is NULL, causing
                # NOT NULL constraint failures if the dependent is NOT NULL.
                has_non_null_dependent_sn7 = False
                for dep_col_name in derive_dependents_sn7.get(col_name_sn7, []):
                    for dep_c in tcfg_sn7.get("columns", []):
                        if dep_c.get("name") == dep_col_name and dep_c.get("null_ratio", 0) < 1.0:
                            has_non_null_dependent_sn7 = True
                            break
                    if has_non_null_dependent_sn7:
                        break
                if not requires_not_null_sn7 and not has_non_null_dependent_sn7:
                    continue
                # Case (c): self-ref FK with IS NOT NULL CHECK — keep
                # null_ratio, restrict the conditional column's choices to
                # the NULL-allowing value. This avoids the chicken-and-egg
                # problem of self-ref FK during initial bulk fill.
                if is_self_ref_fk_sn7 and requires_not_null_sn7:
                    # Find Pattern 30b matching: ``col1 = 'VALUE' OR col IS NOT NULL``
                    # to identify the NULL-allowing value for the conditional column.
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
                    continue  # Keep null_ratio=1.0 for self-ref FK
                # Cases (a) and (b): clear null_ratio and set a non-NULL generator
                c_sn7.pop("null_ratio", None)
                col_type_sn7 = meta_sn7.column_types.get(col_name_sn7, "TEXT")
                # Try to apply a cross-column pattern (Pattern 30b, 30b NOT IN, etc.)
                cross_result_sn7 = _infer_cross_column_config(
                    col_name_sn7, meta_sn7.constraints, meta_sn7.columns,
                    col_type_sn7, fk_cols_set_sn7,
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
                        # Step 1: restrict the Pattern 30b NOT IN
                        # conditional column's choices to EXCLUDE the
                        # NOT IN set values.
                        for c_cond in tcfg_sn7.get("columns", []):
                            if c_cond.get("name") != cond_col_sn7:
                                continue
                            cur_choices = c_cond.get("params", {}).get("choices")
                            if isinstance(cur_choices, list):
                                filtered = [v for v in cur_choices if v not in not_in_values_sn7]
                                if filtered:
                                    c_cond["params"]["choices"] = filtered
                            break
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
                                values_cn = re.findall(r"'([^']*)'", values_str_cn)
                                if not values_cn:
                                    values_cn = [v.strip() for v in values_str_cn.split(",")]
                                allowed_values_per_col_sn7.setdefault(cond_col_cn, set()).update(values_cn)
                        for cond_col_cn, allowed_cn in allowed_values_per_col_sn7.items():
                            for c_cond in tcfg_sn7.get("columns", []):
                                if c_cond.get("name") != cond_col_cn:
                                    continue
                                cur_choices = c_cond.get("params", {}).get("choices")
                                if isinstance(cur_choices, list):
                                    filtered = [v for v in cur_choices if v in allowed_cn]
                                    if filtered:
                                        c_cond["params"]["choices"] = filtered
                                break
                        p30b_notin_matched_sn7 = True
                        break
                    if not p30b_notin_matched_sn7:
                        # No Pattern 30b NOT IN matched — set a safe
                        # non-NULL default.
                        is_fk_sn7 = col_name_sn7 in fk_cols_set_sn7
                        if is_fk_sn7:
                            c_sn7["generator"] = "foreign_key_or_integer"
                            c_sn7["params"] = {}
                        elif "INT" in col_type_sn7.upper():
                            c_sn7["generator"] = "integer"
                            c_sn7["params"] = {"min_value": 0}
                        elif any(k in col_type_sn7.upper() for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")):
                            c_sn7["generator"] = "float"
                            # Use 0.01 (not 0.0) to satisfy ``> 0.0`` CHECKs
                            c_sn7["params"] = {"min_value": 0.01}
                        else:
                            c_sn7["generator"] = "string"
                            c_sn7["params"] = {"min_length": 1, "max_length": 50}

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
            # Detect 2-table circular FK columns (e.g., branches↔employees:
            # branches.manager_id→employees.id AND employees.branch_id→branches.id).
            # topological_sort breaks the cycle by picking one table to fill
            # first, but the first-filled table's FK shared pool is empty,
            # causing foreign_key_or_integer to fall back to random integers
            # — producing FK violations. Marking these columns as
            # ``circular_fk_cols`` sets null_ratio=1.0 in Step 0c below so
            # both sides of the cycle emit NULL, avoiding FK violations.
            # This is a generic fix: any database with a 2-table FK cycle
            # (e.g., branches↔employees, departments↔managers) benefits.
            circular_fk_cols: set[str] = set()
            for fk in meta.foreign_keys:
                for c in fk.get("columns", []):
                    fk_cols_set.add(c)
                if fk.get("ref_table") == table_name:
                    for c in fk.get("columns", []):
                        self_ref_fk_cols.add(c)
                else:
                    # Check for 2-table cycle: current table → ref_table,
                    # and ref_table → current table. If both exist, the FK
                    # column on current table is part of a circular dependency.
                    ref_table_name = fk.get("ref_table")
                    if ref_table_name and ref_table_name in snapshot.tables:
                        ref_meta = snapshot.tables[ref_table_name]
                        for ref_fk in ref_meta.foreign_keys:
                            if ref_fk.get("ref_table") == table_name:
                                for c in fk.get("columns", []):
                                    circular_fk_cols.add(c)
                                break
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
                    cols.append(
                        {
                            "name": col_name,
                            "generator": "foreign_key_or_integer",
                            "params": {},
                            "null_ratio": 1.0,
                        }
                    )
                    continue
                # Step 0c: 2-table circular FK → null_ratio=1.0 (always NULL).
                # When two tables reference each other (e.g.,
                # branches.manager_id→employees.id AND
                # employees.branch_id→branches.id), topological_sort breaks
                # the cycle by filling one table first. The first-filled
                # table's FK shared pool is empty, so foreign_key_or_integer
                # falls back to random integers — causing FK violations.
                # Setting null_ratio=1.0 for BOTH sides of the cycle is the
                # safest approach: it avoids FK violations at the cost of
                # nullable FK columns being NULL. This is acceptable for test
                # data generation (the cycle can be resolved later via UPDATE
                # statements if needed).
                if col_name in circular_fk_cols:
                    cols.append(
                        {
                            "name": col_name,
                            "generator": "foreign_key_or_integer",
                            "params": {},
                            "null_ratio": 1.0,
                        }
                    )
                    continue
                # Step 1: Try cross-column CHECK inference FIRST.
                # Cross-column constraints (e.g., ``unit_price > cost_price``)
                # are stronger than single-column constraints (e.g.,
                # ``unit_price > 0``) and must take priority: if the column
                # has both, derive_from captures the cross-column relation
                # while a bare min_value would silently drop it.
                cross_config = _infer_cross_column_config(
                    col_name, meta.constraints, meta.columns, col_type, fk_cols_set, self_ref_fk_cols,
                    column_types=meta.column_types,
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
                    # Phone-like column + LENGTH(col) >= N (minimum only,
                    # no exact length) → use ``phone`` generator directly.
                    # Faker's phone generator produces numbers like
                    # "+1(555)123-4567" (16 chars) or "555-123-4567"
                    # (12 chars), all naturally >= 7 chars. This satisfies
                    # minimum-length CHECKs while producing semantically
                    # correct phone numbers instead of random alphanumeric
                    # strings. The previous code fell through to ``string``
                    # with ``min_length`` for these columns, producing
                    # gibberish like "Q-zGSPL_DCUrTZCNi" for phone fields.
                    if (
                        gen == "string"
                        and _is_phone_like(col_name)
                        and "min_length" in params
                        and ("max_length" not in params or params["min_length"] != params["max_length"])
                    ):
                        cols.append(
                            {
                                "name": col_name,
                                "generator": "phone",
                                "params": {},
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


def _is_date_only_type(col_type: str) -> bool:
    """Check if a column type is DATE-only (no time component).

    SQLite stores DATE and DATETIME both as TEXT, but the semantic
    distinction matters for derive_from expressions: when a DATE column
    derives from a DATETIME column, the time component is stripped at
    storage time, which can cause julianday diff constraints to fail
    (the diff becomes ``N - time_fraction``, dropping below the
    threshold ``N``).

    Returns True for ``DATE`` but False for ``DATETIME``, ``TIMESTAMP``,
    and ``TIME``.
    """
    t = col_type.upper()
    if "DATETIME" in t or "TIMESTAMP" in t:
        return False
    if "TIME" in t:
        return False  # TIME-only column
    return "DATE" in t


def _is_datetime_type(col_type: str) -> bool:
    """Check if a column type has a time component (DATETIME or TIMESTAMP)."""
    t = col_type.upper()
    return "DATETIME" in t or "TIMESTAMP" in t


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


def _has_cross_column_check(col_name: str, constraints: list[dict[str, Any]]) -> bool:
    """Check if a column has a CHECK constraint referencing other columns.

    Used by the complex CHECK null_ratio safety net (Step 5.5) to detect
    columns that participate in cross-column conditional CHECKs (e.g.,
    ``is_normal = 0 OR test_value IS NULL OR (test_value >= ref_low AND ...)``).
    Such columns are candidates for null_ratio=1.0 when no Pattern (1-41)
    matched the complex CHECK — the ``IS NULL`` branch is the only safe
    fallback.

    Normalizes PostgreSQL CHECK expressions (strips ``::type`` casts) before
    tokenizing. SQL keywords (AND, OR, NOT, NULL, IS, IN, etc.) and numeric
    literals are excluded from the "other column" check.
    """
    for c in constraints:
        if c.get("type") != "check":
            continue
        expr = c.get("expression", "")
        if not expr:
            continue
        # Normalize PG expression (strip ::type casts)
        expr = _normalize_pg_check_expr(expr)
        # Check if this column is referenced
        if col_name not in expr:
            continue
        # Check if ANY other column is referenced (look for word tokens
        # that aren't SQL keywords or numeric literals)
        tokens = set(re.findall(r"\b[a-z_]\w*\b", expr.lower()))
        sql_keywords = {
            "and", "or", "not", "null", "is", "in", "between", "like",
            "case", "when", "then", "else", "end", "abs", "length",
            "date", "time", "timestamp", "true", "false",
        }
        col_refs = tokens - sql_keywords - {col_name.lower()}
        col_refs = {t for t in col_refs if not t.isdigit()}
        if col_refs:
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


def _normalize_pg_check_expr(expr: str) -> str:
    """Normalize PostgreSQL CHECK expression for regex pattern matching.

    PostgreSQL normalizes CHECK expressions in ``information_schema`` by:
    1. Adding ``::type`` casts (e.g., ``::double precision``, ``::text``)
    2. Wrapping RHS of ``=`` in outer parentheses
       (e.g., ``col = (unit_price * quantity + shipping_cost)``)
    3. Wrapping sub-expressions in comparison operators
       (e.g., ``col <= (max_size * 1.5)``)

    These transformations break the regex patterns in
    ``_infer_cross_column_config`` and ``_parse_single_column_check``.
    This function strips casts and outer parentheses to restore the
    original author-intended form.
    """
    # 1. Strip ::type casts (e.g., ::double precision, ::text, ::integer)
    #    Match :: followed by 1-2 word type name.
    expr = re.sub(r"::\w+(?:\s+\w+)?", "", expr)

    # 2. Strip outer parentheses around RHS of = comparison
    #    e.g., "delta = (abs(version_from) * abs(version_to))"
    #    → "delta = abs(version_from) * abs(version_to)"
    #    Uses balanced-paren check to avoid stripping function-call parens.
    m_eq = re.match(r"^(\s*\w+\s*=\s*)\((.+)\)\s*$", expr)
    if m_eq:
        prefix = m_eq.group(1)
        inner = m_eq.group(2)
        depth = 0
        balanced = True
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    balanced = False
                    break
        if balanced and depth == 0:
            expr = prefix + inner

    # 3. Strip parentheses around comparison RHS in compound expressions
    #    e.g., "size_mb <= (max_size * 1.5)" → "size_mb <= max_size * 1.5"
    #    Only strips one level; inner expression must have no parens.
    expr = re.sub(r"((?:>=|<=|!=|>|<)\s*)\(([^()]+)\)", r"\1\2", expr)

    return expr


def _normalize_constraints(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of constraints with PostgreSQL-normalized expressions.

    Creates shallow copies of constraint dicts with normalized ``expression``
    fields, so the original list is not mutated.
    """
    result: list[dict[str, Any]] = []
    for c in constraints:
        if c.get("type") == "check" and c.get("expression"):
            nc = dict(c)
            nc["expression"] = _normalize_pg_check_expr(c["expression"])
            result.append(nc)
        else:
            result.append(c)
    return result


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
    # Normalize constraints (strip PG ::type casts and outer parens).
    constraints = _normalize_constraints(constraints)
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
    # Normalize PG expression (strip ::type casts and outer parens).
    expr = _normalize_pg_check_expr(expr)
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

    # Pattern: col = ANY (ARRAY['a'::text, 'b'::text, ...]) — PostgreSQL
    # normalizes ``col IN ('a', 'b')`` to this form in information_schema.
    # The ``::type`` casts are stripped from each value. Example:
    #   status = ANY (ARRAY['active'::text, 'inactive'::text, ...])
    # Without this pattern, all PostgreSQL IN-constrained columns would miss
    # CHECK inference, causing the L3 exact match ``choices: [0, 1]`` to leak
    # through for every ``status`` column.
    m = re.match(
        rf"^\s*{col}\s*=\s*ANY\s*\(\s*ARRAY\s*\[\s*(.+?)\s*\]\s*\)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        inner = m.group(1)
        # Extract quoted string values (strip ::type casts)
        choices = re.findall(r"'([^']*)'", inner)
        if choices:
            return ("choice", {"choices": choices})
        # Try numeric values
        nums = re.findall(r"\b(-?\d+)\b", inner)
        if nums:
            nums_int = [int(n) for n in nums]
            if len(nums_int) == 2 and set(nums_int) == {0, 1}:
                return ("boolean", {})
            return ("choice", {"choices": nums_int})

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
    self_ref_fk_cols: set[str] | None = None,
    column_types: dict[str, str] | None = None,
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
    # Normalize constraints (strip PG ::type casts and outer parens) so
    # regex patterns can match PostgreSQL-normalized CHECK expressions.
    constraints = _normalize_constraints(constraints)
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

    # Pattern 22c: col >= col2 * CONST1 AND col <= col2 * CONST2 (dual multiplier
    # bounds — two separate CHECK constraints that together define a range
    # as a multiple of col2). This must be checked BEFORE the per-constraint
    # loop because Pattern 7b would match the lower bound alone and return
    # ``value * CONST1`` (a fixed multiplier), ignoring the upper bound.
    # e.g., base_price_yearly >= base_price_monthly * 10
    #       base_price_yearly <= base_price_monthly * 12
    # Derive from col2, multiply by random_float(CONST1, CONST2).
    lower_mult: float | None = None
    upper_mult: float | None = None
    mult_src_col: str | None = None
    for c in constraints:
        if c.get("type") != "check":
            continue
        expr_c = c.get("expression", "")
        # Lower bound: col >= col2 * CONST1
        m_low = re.match(
            rf"^\s*{col}\s*>=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
            expr_c,
            re.IGNORECASE,
        )
        if m_low and m_low.group(1) in col_set and m_low.group(1) != col_name:
            lower_mult = float(m_low.group(2))
            mult_src_col = m_low.group(1)
        # Upper bound: col <= col2 * CONST2
        m_up = re.match(
            rf"^\s*{col}\s*<=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
            expr_c,
            re.IGNORECASE,
        )
        if m_up and m_up.group(1) in col_set and m_up.group(1) != col_name:
            upper_mult = float(m_up.group(2))
            if mult_src_col is None:
                mult_src_col = m_up.group(1)
            elif mult_src_col != m_up.group(1):
                # Different source columns — not a dual-bound pattern
                upper_mult = None
    if lower_mult is not None and upper_mult is not None and mult_src_col is not None and lower_mult <= upper_mult:
        return {
            "derive_from": mult_src_col,
            "expression": f"value * random_float({lower_mult}, {upper_mult})",
        }

    # Pattern 40: self-ref FK conditional equality — when col2 is a self-ref
    # FK (always NULL at fill time) and constraint is
    # ``col1 = VALUE OR col2 IS NOT NULL``, col1 must be VALUE.
    # Since col2 is always NULL, ``col2 IS NOT NULL`` is always FALSE, so
    # ``col1 = VALUE`` must be TRUE. Force col1 to a choice with only VALUE.
    # This must be a PRE-LOOP scan because it applies to col1 (not col2), and
    # the per-constraint loop might match a less restrictive pattern first.
    # e.g., org_type = 'root' OR parent_id IS NOT NULL (parent_id is self-ref FK)
    if self_ref_fk_cols:
        for c in constraints:
            if c.get("type") != "check":
                continue
            expr_p40 = c.get("expression", "")
            m_p40 = re.match(
                rf"^\s*{col}\s*=\s*'([^']+)'\s+OR\s+(\w+)\s+IS\s+NOT\s+NULL\s*$",
                expr_p40,
                re.IGNORECASE,
            )
            if m_p40:
                val_p40 = m_p40.group(1)
                other_col_p40 = m_p40.group(2)
                if other_col_p40 in self_ref_fk_cols and other_col_p40 != col_name:
                    return {
                        "generator": "choice",
                        "params": {"choices": [val_p40]},
                    }
            # Pattern 40 (int variant): col = INT_VALUE OR other_col IS NOT NULL
            # e.g., level = 1 OR parent_id IS NOT NULL (parent_id is self-ref FK)
            # Same semantics as the string variant but with an unquoted integer.
            m_p40_int = re.match(
                rf"^\s*{col}\s*=\s*(\d+)\s+OR\s+(\w+)\s+IS\s+NOT\s+NULL\s*$",
                expr_p40,
                re.IGNORECASE,
            )
            if m_p40_int:
                val_p40_int = int(m_p40_int.group(1))
                other_col_p40_int = m_p40_int.group(2)
                if other_col_p40_int in self_ref_fk_cols and other_col_p40_int != col_name:
                    return {
                        "generator": "choice",
                        "params": {"choices": [val_p40_int]},
                    }

    # Pattern 1b pre-loop scan: 3-way OR constraints must be checked BEFORE
    # the per-constraint loop. Without this, a Pattern 1 (2-way OR) constraint
    # on the same column would match first and return early, preventing
    # Pattern 1b from ever being evaluated.
    # e.g., api_keys.revoked_at has both:
    #   - revoked_at IS NULL OR revoked_at >= created_at  (Pattern 1, 2-way)
    #   - revoked_at IS NULL OR expires_at IS NULL OR revoked_at <= expires_at  (Pattern 1b, 3-way)
    # Pattern 1b is more restrictive (involves 2 other columns), so it wins.
    #
    # Lower bound awareness: when the upper-bound branch (<= or <) is taken,
    # scan all constraints for a sibling lower-bound pattern
    # ``col IS NULL OR col (>=|>) other_col2``. If found, the subtracted /
    # decremented expression may produce a value below the lower bound
    # (e.g., revoked_at derived from expires_at minus up to 365 days can
    # land before created_at). Wrap with ``max(result, row['other_col2'])``
    # so the value respects both bounds simultaneously. ``max`` is in
    # SAFE_FUNCTIONS (see core/expression.py). This is only applied to the
    # upper-bound branch; the lower-bound branch (>=, >) adds to ``value``
    # and therefore cannot violate a sibling upper bound that Pattern 1b
    # already enforces via the derive_from source column.
    lower_bound_col_p1b: str | None = None
    for lc_p1b in constraints:
        if lc_p1b.get("type") != "check":
            continue
        lc_expr_p1b = lc_p1b.get("expression", "")
        m_low_p1b = re.match(
            rf"^\s*{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>)\s*(\w+)\s*$",
            lc_expr_p1b,
            re.IGNORECASE,
        )
        if m_low_p1b:
            lb_col_p1b = m_low_p1b.group(2)
            if lb_col_p1b in col_set and lb_col_p1b != col_name:
                lower_bound_col_p1b = lb_col_p1b
                break

    # Literal bound awareness: scan for literal numeric bounds on this column.
    # ``col IS NULL OR col (>=|>) X`` (X is a number) → lower bound literal
    # ``col IS NULL OR col (<=|<) Y`` (Y is a number) → upper bound literal
    # When the Pattern 1b branch expression could violate a literal bound,
    # wrap with ``max(result, X)`` / ``min(result, Y)`` to enforce both.
    # e.g., R3.warehouses.temperature_max has:
    #   - temperature_max IS NULL OR temperature_max <= 40.0  (literal upper)
    #   - Pattern 1b: temperature_max > temperature_min → value * 1.01-2.0
    # Without min() wrapping, value * 2.0 can exceed 40.0.
    lower_bound_literal_p1b: float | None = None
    upper_bound_literal_p1b: float | None = None
    for bc_p1b in constraints:
        if bc_p1b.get("type") != "check":
            continue
        bc_expr_p1b = bc_p1b.get("expression", "")
        m_low_lit = re.match(
            rf"^\s*{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>)\s*(-?\d+(?:\.\d+)?)\s*$",
            bc_expr_p1b,
            re.IGNORECASE,
        )
        if m_low_lit and lower_bound_literal_p1b is None:
            lower_bound_literal_p1b = float(m_low_lit.group(2))
        m_up_lit = re.match(
            rf"^\s*{col}\s+IS\s+NULL\s+OR\s+{col}\s*(<=|<)\s*(-?\d+(?:\.\d+)?)\s*$",
            bc_expr_p1b,
            re.IGNORECASE,
        )
        if m_up_lit and upper_bound_literal_p1b is None:
            upper_bound_literal_p1b = float(m_up_lit.group(2))

    for c in constraints:
        if c.get("type") != "check":
            continue
        expr_p1b = c.get("expression", "")
        if not re.search(rf"\b{col}\b", expr_p1b, re.IGNORECASE):
            continue
        m_p1b = re.search(
            rf"{col}\s+IS\s+NULL\s+OR\s+(\w+)\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
            expr_p1b,
            re.IGNORECASE,
        )
        if not m_p1b:
            # Reversed ordering: other IS NULL OR col IS NULL OR col OP other
            # e.g., temperature_min IS NULL OR temperature_max IS NULL OR temperature_max > temperature_min
            m_p1b = re.search(
                rf"(\w+)\s+IS\s+NULL\s+OR\s+{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
                expr_p1b,
                re.IGNORECASE,
            )
        if m_p1b:
            other_col_p1b_pre = m_p1b.group(1)
            op_p1b_pre = m_p1b.group(2)
            other_col_ref_p1b_pre = m_p1b.group(3)
            if (
                other_col_p1b_pre == other_col_ref_p1b_pre
                and other_col_p1b_pre in col_set
                and other_col_p1b_pre != col_name
            ):
                if is_date_col or _is_date_column(other_col_p1b_pre):
                    if op_p1b_pre in (">=", ">"):
                        return {
                            "derive_from": other_col_p1b_pre,
                            "expression": "None if value is None else value + timedelta(days=random_int(1, 365))",
                        }
                    days_p1b_pre = "0" if op_p1b_pre == "<=" else "1"
                    inner_p1b = f"value - timedelta(days=random_int({days_p1b_pre}, 365))"
                    if lower_bound_col_p1b:
                        inner_p1b = f"max({inner_p1b}, row['{lower_bound_col_p1b}'])"
                    return {
                        "derive_from": other_col_p1b_pre,
                        "expression": f"None if value is None else {inner_p1b}",
                    }
                if is_float_type:
                    if op_p1b_pre == ">=":
                        inner_p1b_ge = "value + random_float(0, 100)"
                        if upper_bound_literal_p1b is not None:
                            inner_p1b_ge = f"min({inner_p1b_ge}, {upper_bound_literal_p1b})"
                        return {
                            "derive_from": other_col_p1b_pre,
                            "expression": f"None if value is None else {inner_p1b_ge}",
                        }
                    if op_p1b_pre == ">":
                        # Addition (not multiplication) ensures result > value for
                        # ALL signs of value. ``value * 1.01`` makes negative values
                        # MORE negative (e.g., -20.0 * 1.01 = -20.2 < -20.0), violating
                        # ``col > other_col``. ``value + delta`` (delta > 0) is
                        # sign-agnostic and always satisfies the strict inequality.
                        inner_p1b_gt = "value + random_float(0.01, 100.0)"
                        if upper_bound_literal_p1b is not None:
                            # When ``value >= upper_bound``, the constraint
                            # ``col > value AND col <= upper_bound`` is unsolvable
                            # (no number is simultaneously > value and <= upper_bound
                            # when value >= upper_bound) → return None (NULL).
                            # Otherwise, min() caps the result to upper_bound, which
                            # is still > value since value < upper_bound.
                            inner_p1b_gt = (
                                f"None if value >= {upper_bound_literal_p1b} else "
                                f"min({inner_p1b_gt}, {upper_bound_literal_p1b})"
                            )
                        return {
                            "derive_from": other_col_p1b_pre,
                            "expression": f"None if value is None else {inner_p1b_gt}",
                        }
                    if op_p1b_pre == "<=":
                        # Subtraction ensures result <= value for ALL signs.
                        # ``value * 0.5`` for negative values produces a LARGER value
                        # (e.g., -20.0 * 0.5 = -10.0 > -20.0), violating ``col <= other_col``.
                        # ``value - delta`` (delta >= 0) is sign-agnostic.
                        inner_p1b_f = "value - random_float(0, 100)"
                        if lower_bound_col_p1b:
                            inner_p1b_f = f"max({inner_p1b_f}, row['{lower_bound_col_p1b}'])"
                        if lower_bound_literal_p1b is not None:
                            inner_p1b_f = f"max({inner_p1b_f}, {lower_bound_literal_p1b})"
                        return {
                            "derive_from": other_col_p1b_pre,
                            "expression": f"None if value is None else {inner_p1b_f}",
                        }
                    # op_p1b_pre == "<" — strict less-than
                    inner_p1b_f_lt = "value - random_float(0.01, 100.0)"
                    if lower_bound_col_p1b:
                        inner_p1b_f_lt = f"max({inner_p1b_f_lt}, row['{lower_bound_col_p1b}'])"
                    if lower_bound_literal_p1b is not None:
                        inner_p1b_f_lt = f"max({inner_p1b_f_lt}, {lower_bound_literal_p1b})"
                    return {
                        "derive_from": other_col_p1b_pre,
                        "expression": f"None if value is None else {inner_p1b_f_lt}",
                    }
                if op_p1b_pre == ">=":
                    inner_p1b_ige = "value + random_int(0, 100)"
                    if upper_bound_literal_p1b is not None:
                        inner_p1b_ige = f"min({inner_p1b_ige}, {int(upper_bound_literal_p1b)})"
                    return {
                        "derive_from": other_col_p1b_pre,
                        "expression": f"None if value is None else {inner_p1b_ige}",
                    }
                if op_p1b_pre == ">":
                    inner_p1b_igt = "value + random_int(1, 100)"
                    if upper_bound_literal_p1b is not None:
                        inner_p1b_igt = f"min({inner_p1b_igt}, {int(upper_bound_literal_p1b)})"
                    return {
                        "derive_from": other_col_p1b_pre,
                        "expression": f"None if value is None else {inner_p1b_igt}",
                    }
                if op_p1b_pre == "<=":
                    inner_p1b_i = "value - random_int(0, 100)"
                    if lower_bound_col_p1b:
                        inner_p1b_i = f"max({inner_p1b_i}, row['{lower_bound_col_p1b}'])"
                    if lower_bound_literal_p1b is not None:
                        inner_p1b_i = f"max({inner_p1b_i}, {int(lower_bound_literal_p1b)})"
                    return {
                        "derive_from": other_col_p1b_pre,
                        "expression": f"None if value is None else {inner_p1b_i}",
                    }
                inner_p1b_i_lt = "value - random_int(1, 100)"
                if lower_bound_col_p1b:
                    inner_p1b_i_lt = f"max({inner_p1b_i_lt}, row['{lower_bound_col_p1b}'])"
                if lower_bound_literal_p1b is not None:
                    inner_p1b_i_lt = f"max({inner_p1b_i_lt}, {int(lower_bound_literal_p1b)})"
                return {
                    "derive_from": other_col_p1b_pre,
                    "expression": f"None if value is None else {inner_p1b_i_lt}",
                }

    # Pattern 30 pre-loop scan: ``col1 != VALUE OR col IS NULL`` must be
    # checked BEFORE the per-constraint loop. Without this, a Pattern 1
    # constraint (``col IS NULL OR col >= other_col``) on the same column
    # would match first and return early, preventing Pattern 30 from ever
    # being evaluated.
    # e.g., R2.prescriptions.dispensed_at has both:
    #   - status != 'cancelled' OR dispensed_at IS NULL  (Pattern 30)
    #   - dispensed_at IS NULL OR dispensed_at >= prescribed_at  (Pattern 1)
    # Pattern 1 would make dispensed_at always non-NULL, violating Pattern 30
    # when status == 'cancelled'.
    #
    # Sibling Pattern 1 awareness: when both Pattern 30 and Pattern 1 exist,
    # derive from Pattern 1's source column (other_col) with a conditional
    # NULL: ``None if row['col1'] == 'VALUE' else (value + timedelta(...))``.
    # This satisfies BOTH constraints simultaneously:
    #   - Pattern 30: when col1 == VALUE, col is None ✓
    #   - Pattern 1: when col is not None, col >= other_col ✓
    # The ``row['col1']`` access is supported by the expression engine.
    #
    # Datetime fix: without a sibling Pattern 1, datetime columns return
    # None for BOTH branches (not 0, which is invalid for datetime). The
    # per-constraint Pattern 30 code handles FK and non-datetime non-FK
    # columns.
    p30_other_col: str | None = None
    p30_val_str: str | None = None
    p30_sibling_col: str | None = None
    for c_p30 in constraints:
        if c_p30.get("type") != "check":
            continue
        expr_p30 = c_p30.get("expression", "")
        m_p30 = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s+IS\s+NULL\s*$",
            expr_p30,
            re.IGNORECASE,
        )
        if m_p30:
            p30_other_col = m_p30.group(1)
            p30_val_str = m_p30.group(2)
            if p30_other_col not in col_set or p30_other_col == col_name:
                p30_other_col = None
                continue
            # Scan for sibling Pattern 1: col IS NULL OR col (>=|>) other_col2
            for c_p30sib in constraints:
                if c_p30sib.get("type") != "check":
                    continue
                expr_p30sib = c_p30sib.get("expression", "")
                m_p30sib = re.match(
                    rf"^\s*{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>)\s*(\w+)\s*$",
                    expr_p30sib,
                    re.IGNORECASE,
                )
                if m_p30sib:
                    sib_col = m_p30sib.group(2)
                    if sib_col in col_set and sib_col != col_name:
                        p30_sibling_col = sib_col
                        break
            break

    if p30_other_col is not None and p30_val_str is not None:
        # Case 1: Pattern 30 + sibling Pattern 1 → cross-column derive
        if p30_sibling_col is not None:
            if is_date_col or _is_date_column(p30_sibling_col):
                return {
                    "derive_from": p30_sibling_col,
                    "expression": (
                        f"None if row['{p30_other_col}'] == '{p30_val_str}' else "
                        f"(None if value is None else value + timedelta(days=random_int(1, 365)))"
                    ),
                }
            if is_float_type:
                return {
                    "derive_from": p30_sibling_col,
                    "expression": (
                        f"None if row['{p30_other_col}'] == '{p30_val_str}' else "
                        f"(None if value is None else value + random_float(0, 100))"
                    ),
                }
            return {
                "derive_from": p30_sibling_col,
                "expression": (
                    f"None if row['{p30_other_col}'] == '{p30_val_str}' else "
                    f"(None if value is None else value + random_int(0, 100))"
                ),
            }
        # Case 2: Pattern 30 + datetime column (no sibling Pattern 1) → always None
        # 0 is not a valid datetime value; None (NULL) is always safe.
        if is_date_col:
            return {
                "derive_from": p30_other_col,
                "expression": f"None if value == '{p30_val_str}' else None",
            }

    # Pattern 27 pre-loop scan: N-way conditional range must be checked BEFORE
    # the per-constraint loop. Without this, a Pattern 18 constraint
    # (``other_col != 'VALUE' OR col = X``) on the same column would match
    # first and return early, preventing Pattern 27 from ever being evaluated.
    # e.g., R5.enrollments.progress_percent has both:
    #   - status != 'completed' OR progress_percent = 100  (Pattern 18)
    #   - status = 'active' AND progress_percent >= 0 OR status = 'completed'
    #     AND progress_percent >= 100 OR status = 'dropped' AND progress_percent < 100
    #     (Pattern 27, multi-clause)
    # Pattern 27 is more specific (per-status ranges), so it wins.
    # Guard: skip if the constraint has dual bounds per clause (Pattern 36).
    # Pattern 36 clauses look like ``col >= X AND col < Y`` (two comparisons
    # on col per clause). If the number of ``col OP`` occurrences is more than
    # the number of enum assignments, it's Pattern 36, not Pattern 27.
    for c_p27_pre in constraints:
        if c_p27_pre.get("type") != "check":
            continue
        expr_p27_pre = c_p27_pre.get("expression", "")
        if " OR " not in expr_p27_pre or " AND " not in expr_p27_pre:
            continue
        if not re.search(rf"\b{col}\b", expr_p27_pre, re.IGNORECASE):
            continue
        clause_re_p27_pre = (
            rf"(\w+)\s*=\s*'([^']+)'\s+AND\s+{col}\s*"
            r"(>=|<=|>|<)\s*(-?[0-9]+(?:\.[0-9]+)?)"
        )
        clauses_p27_pre = re.findall(clause_re_p27_pre, expr_p27_pre)
        if len(clauses_p27_pre) >= 2:
            other_col_p27_pre = clauses_p27_pre[0][0]
            if (
                other_col_p27_pre in col_set
                and other_col_p27_pre != col_name
                and all(cl[0] == other_col_p27_pre for cl in clauses_p27_pre)
            ):
                # Guard: count enum assignments vs col comparisons. If
                # comparisons > assignments, it's Pattern 36 (dual bounds).
                enum_count = len(re.findall(
                    rf"{other_col_p27_pre}\s*=\s*'[^']+'", expr_p27_pre, re.IGNORECASE
                ))
                col_cmp_count = len(re.findall(
                    rf"\b{col}\s*(>=|<=|>|<)\s*", expr_p27_pre, re.IGNORECASE
                ))
                if col_cmp_count > enum_count:
                    continue  # Pattern 36 — skip, let per-loop Pattern 36 handle it
                parts_p27_pre: list[str] = []
                for _other, vi, opi, xi in clauses_p27_pre[:-1]:
                    xi_num = float(xi)
                    rand_expr = _range_expr_for_op(opi, xi_num)
                    parts_p27_pre.append(f"{rand_expr} if value == '{vi}'")
                _other, _last_vi, last_op, last_xi = clauses_p27_pre[-1]
                last_rand = _range_expr_for_op(last_op, float(last_xi))
                expr_chain = last_rand
                for idx in range(len(parts_p27_pre) - 1, -1, -1):
                    expr_chain = f"{parts_p27_pre[idx]} else ({expr_chain})"
                # Apply column-level CHECK bounds (min/max) as wrappers.
                # Pattern 27 clause ranges (e.g., ``>= 100`` →
                # ``random_float(100, 200)``) may exceed the column's
                # single-column CHECK (e.g., ``<= 100``). Wrap with
                # ``min(result, max_val)`` / ``max(result, min_val)`` to
                # enforce both Pattern 27 clause ranges AND column-level
                # bounds simultaneously. ``min``/``max`` are in SAFE_FUNCTIONS.
                col_check = _infer_from_check_constraints(col_name, constraints, all_columns)
                if col_check is not None:
                    _ck_gen, ck_params = col_check
                    max_val = ck_params.get("max_value")
                    min_val = ck_params.get("min_value")
                    if max_val is not None:
                        expr_chain = f"min({expr_chain}, {max_val})"
                    if min_val is not None:
                        expr_chain = f"max({expr_chain}, {min_val})"
                return {
                    "derive_from": other_col_p27_pre,
                    "expression": expr_chain,
                }

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
        # IMPORTANT: the negative lookbehind ``(?<![<>])`` ensures ``=`` is not
        # part of ``<=`` or ``>=``. Without this, the regex would match
        # ``col IS NULL OR col <= expr`` (a comparison, not an equality),
        # incorrectly returning null_ratio=1.0. This caused R7
        # claims.approved_amount to be all-NULL because Pattern 4 matched
        # ``approved_amount IS NULL OR approved_amount <= claim_amount``
        # before Pattern 30b NOT IN could match
        # ``status NOT IN ('approved','settled') OR approved_amount IS NOT NULL``.
        if re.search(rf"{col}\s+IS\s+NULL\s+OR\s+{col}\s*(?<![<>])=", expr, re.IGNORECASE):
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

        # Pattern 1b: 3-way OR — col IS NULL OR other IS NULL OR col (>=|>|<=|<) other
        # This is Pattern 1 extended with an ``other_col IS NULL`` escape clause.
        # When other_col is NULL, col can be anything (including NULL). The
        # expression must guard against ``value is None`` to avoid TypeError
        # when subtracting timedelta or multiplying None.
        # e.g., revoked_at IS NULL OR expires_at IS NULL OR revoked_at <= expires_at
        # Also handles reversed ordering: other IS NULL OR col IS NULL OR col OP other
        # e.g., temperature_min IS NULL OR temperature_max IS NULL OR temperature_max > temperature_min
        m = re.search(
            rf"{col}\s+IS\s+NULL\s+OR\s+(\w+)\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
            expr,
            re.IGNORECASE,
        )
        if not m:
            m = re.search(
                rf"(\w+)\s+IS\s+NULL\s+OR\s+{col}\s+IS\s+NULL\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)",
                expr,
                re.IGNORECASE,
            )
        if m:
            other_col_p1b = m.group(1)
            op_p1b = m.group(2)
            other_col_ref_p1b = m.group(3)
            if other_col_p1b == other_col_ref_p1b and other_col_p1b in col_set and other_col_p1b != col_name:
                if is_date_col or _is_date_column(other_col_p1b):
                    if op_p1b in (">=", ">"):
                        return {
                            "derive_from": other_col_p1b,
                            "expression": "None if value is None else value + timedelta(days=random_int(1, 365))",
                        }
                    days_p1b = "0" if op_p1b == "<=" else "1"
                    return {
                        "derive_from": other_col_p1b,
                        "expression": f"None if value is None else value - timedelta(days=random_int({days_p1b}, 365))",
                    }
                if is_float_type:
                    if op_p1b == ">=":
                        return {
                            "derive_from": other_col_p1b,
                            "expression": "None if value is None else value + random_float(0, 100)",
                        }
                    if op_p1b == ">":
                        # Addition (not multiplication) — see pre-loop scan comment.
                        # ``value * 1.01`` violates ``col > other_col`` for negative values.
                        return {
                            "derive_from": other_col_p1b,
                            "expression": "None if value is None else value + random_float(0.01, 100.0)",
                        }
                    if op_p1b == "<=":
                        # Subtraction — ``value * 0.5`` violates ``col <= other_col`` for negatives.
                        return {
                            "derive_from": other_col_p1b,
                            "expression": "None if value is None else value - random_float(0, 100)",
                        }
                    return {
                        "derive_from": other_col_p1b,
                        "expression": "None if value is None else value - random_float(0.01, 100.0)",
                    }
                if op_p1b == ">=":
                    return {
                        "derive_from": other_col_p1b,
                        "expression": "None if value is None else value + random_int(0, 100)",
                    }
                if op_p1b == ">":
                    return {
                        "derive_from": other_col_p1b,
                        "expression": "None if value is None else value + random_int(1, 100)",
                    }
                if op_p1b == "<=":
                    return {
                        "derive_from": other_col_p1b,
                        "expression": "None if value is None else value - random_int(0, 100)",
                    }
                return {
                    "derive_from": other_col_p1b,
                    "expression": "None if value is None else value - random_int(1, 100)",
                }

        # Pattern 1: col IS NULL OR col (>=|>|<=|<) other_col (ordering with NULL escape)
        # Also handles: col IS NULL OR other IS NULL OR col >= other
        # e.g., termination_date IS NULL OR termination_date >= hire_date
        # e.g., due_date IS NULL OR start_date IS NULL OR due_date >= start_date
        # e.g., assessment_price IS NULL OR assessment_price <= listing_price
        #
        # Single-column range-bound awareness: before applying Pattern 1,
        # scan all constraints for a single-column range CHECK on this column
        # (e.g., ``col IS NULL OR (col >= 40 AND col <= 150)``). When found,
        # the Pattern 1 expression (e.g., ``value - random_int(1, 100)``) is
        # wrapped with ``max(LOWER, min(UPPER, expr))`` to enforce both the
        # cross-column ordering AND the single-column range simultaneously.
        # Without this, ``value - random_int(1, 100)`` can produce values
        # outside [LOWER, UPPER] (e.g., high=60 → low=-40, violating >= 40).
        p1_lower: float | int | None = None
        p1_upper: float | int | None = None
        for rc_p1 in constraints:
            if rc_p1.get("type") != "check":
                continue
            rc_expr_p1 = rc_p1.get("expression", "")
            # Match: col IS NULL OR (col >= X AND col <= Y)
            m_range_p1 = re.match(
                rf"^\s*{col}\s+IS\s+NULL\s+OR\s*\(\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*\)\s*$",
                rc_expr_p1,
                re.IGNORECASE,
            )
            if not m_range_p1:
                # Also match: col >= X AND col <= Y (without IS NULL prefix)
                m_range_p1 = re.match(
                    rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
                    rc_expr_p1,
                    re.IGNORECASE,
                )
            if m_range_p1:
                low_str_p1 = m_range_p1.group(1)
                high_str_p1 = m_range_p1.group(2)
                if "." in low_str_p1 or "." in high_str_p1:
                    p1_lower = float(low_str_p1)
                    p1_upper = float(high_str_p1)
                else:
                    p1_lower = int(low_str_p1)
                    p1_upper = int(high_str_p1)
                break
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
                # Helper: wrap expression with single-column range bounds
                # (p1_lower, p1_upper) if they exist. This ensures the
                # cross-column expression respects the single-column CHECK
                # range simultaneously.
                def _wrap_p1_bounds(inner_expr: str) -> str:
                    if p1_lower is not None and p1_upper is not None:
                        return f"max({p1_lower}, min({p1_upper}, {inner_expr}))"
                    return inner_expr

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
                    # Float columns: use additive offsets (NOT multiplication).
                    # Multiplication ``value * factor`` only produces ``result > value``
                    # when ``value > 0``; for negative values it reverses the inequality.
                    # Addition/subtraction is sign-agnostic and always correct.
                    if op == ">=":
                        return {
                            "derive_from": other_col,
                            "expression": _wrap_p1_bounds("value + random_float(0, 100)"),
                        }
                    if op == ">":
                        return {
                            "derive_from": other_col,
                            "expression": _wrap_p1_bounds("value + random_float(0.01, 100.0)"),
                        }
                    if op == "<=":
                        return {
                            "derive_from": other_col,
                            "expression": _wrap_p1_bounds("value - random_float(0, 100)"),
                        }
                    # op == "<"
                    return {
                        "derive_from": other_col,
                        "expression": _wrap_p1_bounds("value - random_float(0.01, 100.0)"),
                    }
                # Integer columns: use additive offsets
                if op == ">=":
                    return {
                        "derive_from": other_col,
                        "expression": _wrap_p1_bounds("value + random_int(0, 100)"),
                    }
                if op == ">":
                    return {
                        "derive_from": other_col,
                        "expression": _wrap_p1_bounds("value + random_int(1, 100)"),
                    }
                if op == "<=":
                    return {
                        "derive_from": other_col,
                        "expression": _wrap_p1_bounds("value - random_int(0, 100)"),
                    }
                # op == "<"
                return {
                    "derive_from": other_col,
                    "expression": _wrap_p1_bounds("value - random_int(1, 100)"),
                }

        # Pattern 1 (DATE-on-left variant): col IS NULL OR DATE(col) OP other_col
        # e.g., paid_at IS NULL OR DATE(paid_at) >= due_date
        # Same semantics as Pattern 1 but with a DATE() wrapper on the left
        # column. When col is not NULL, DATE(col) must satisfy the comparison
        # with other_col. The expression generates col = other_col + positive
        # timedelta (for >=, >) or other_col - timedelta (for <=, <).
        m_date_left = re.search(
            rf"{col}\s+IS\s+NULL\s+OR\s+DATE\s*\(\s*{col}\s*\)\s*(>=|>|<=|<)\s*(\w+)",
            expr,
            re.IGNORECASE,
        )
        if m_date_left:
            op_dl = m_date_left.group(1)
            other_col_dl = m_date_left.group(2)
            if (other_col_dl in col_set and other_col_dl != col_name
                    and (is_date_col or _is_date_column(other_col_dl))):
                if op_dl in (">=", ">"):
                    return {
                        "derive_from": other_col_dl,
                        "expression": "value + timedelta(days=random_int(1, 365))",
                    }
                days_dl = "0" if op_dl == "<=" else "1"
                return {
                    "derive_from": other_col_dl,
                    "expression": f"value - timedelta(days=random_int({days_dl}, 365))",
                }

        # Pattern 39: col1 IS NULL OR col <= col2 + col3 (compound addition upper bound)
        # e.g., quota_limit IS NULL OR metric_value <= quota_limit + overage_amount
        # Semantics: when col1 (quota_limit) is NULL, col can be anything;
        # otherwise col must be <= col2 + col3. Derive from col2 (quota_limit):
        # when value is None, return a safe random; otherwise return
        # (value + row['col3']) * random_factor to stay under the bound.
        m = re.match(
            rf"^\s*(\w+)\s+IS\s+NULL\s+OR\s+{col}\s*<=\s*(\w+)\s*\+\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col2_p39 = m.group(2)
            col3_p39 = m.group(3)
            if col2_p39 in col_set and col3_p39 in col_set and col_name not in (col2_p39, col3_p39):
                return {
                    "derive_from": col2_p39,
                    "expression": (f"None if value is None else (value + row['{col3_p39}']) * random_float(0.0, 1.0)"),
                }

        # Pattern 39 (no-NULL variant): col <= col2 + col3 (compound addition
        # upper bound without NULL escape).
        # e.g., available_balance <= balance + overdraft_limit
        # Same arithmetic as Pattern 39 but without the ``col1 IS NULL OR``
        # prefix — col must ALWAYS satisfy ``col <= col2 + col3``.
        m_nn_p39 = re.match(
            rf"^\s*{col}\s*<=\s*(\w+)\s*\+\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m_nn_p39:
            col2_p39nn = m_nn_p39.group(1)
            col3_p39nn = m_nn_p39.group(2)
            if (col2_p39nn in col_set and col3_p39nn in col_set
                    and col_name not in (col2_p39nn, col3_p39nn)):
                return {
                    "derive_from": col2_p39nn,
                    "expression": f"(value + row['{col3_p39nn}']) * random_float(0.0, 1.0)",
                }

        # Pattern 41: col (>=|>|<=|<) DATE(other_col) — standalone comparison
        # with DATE() function wrapper. SQLite and PostgreSQL both support
        # ``DATE(col)`` to coerce a datetime/text to a date. The wrapper must
        # be stripped to extract the column name, then the comparison is
        # treated like Pattern 2/3/8 (standalone col vs other_col).
        # e.g., due_date >= DATE(period_start)
        # e.g., end_date <= DATE(start_date)  (unusual but valid)
        m = re.match(
            rf"^\s*{col}\s*(>=|>|<=|<)\s*DATE\s*\(\s*(\w+)\s*\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            op_p41 = m.group(1)
            other_col_p41 = m.group(2)
            if other_col_p41 in col_set and other_col_p41 != col_name:
                if is_date_col or _is_date_column(other_col_p41):
                    if op_p41 in (">=", ">"):
                        # Scan for date-difference constraints like
                        # ``col - other_col >= N`` or ``col - other_col > N``
                        # which require a minimum day offset. Use the max N
                        # found as the lower bound (N+1 for strict >).
                        # e.g., ``maturity_date - disbursed_at >= 30`` →
                        # lower bound 30 days.
                        # Also matches the SQLite-compatible julianday() form:
                        # ``julianday(col) - julianday(other_col) >= N``
                        # (standard ISO date subtraction returns 0 in SQLite,
                        # so schemas targeting SQLite should use julianday()).
                        min_days_p41 = 1
                        for c_p41 in constraints:
                            if c_p41 is c or c_p41.get("type") != "check":
                                continue
                            expr_p41_diff = c_p41.get("expression", "")
                            m_p41_diff = re.search(
                                rf"(?:julianday\()?{col}\)?\s*-\s*(?:julianday\()?{other_col_p41}\)?\s*(>=|>)\s*(\d+)",
                                expr_p41_diff,
                                re.IGNORECASE,
                            )
                            if m_p41_diff:
                                diff_op = m_p41_diff.group(1)
                                diff_n = int(m_p41_diff.group(2))
                                bound = diff_n if diff_op == ">=" else diff_n + 1
                                if bound > min_days_p41:
                                    min_days_p41 = bound
                        # DATE-vs-DATETIME compensation: when the target column
                        # is DATE-only (no time component) and the source column
                        # is DATETIME (has time component), the stored target
                        # value loses its time component (set to midnight),
                        # while the source retains its time. This causes the
                        # julianday diff to be ``N - time_fraction``, which can
                        # drop below the threshold ``N`` when random_int returns
                        # exactly N. Add 1 extra day to guarantee the constraint
                        # is always satisfied.
                        # e.g., maturity_date (DATE) derives from disbursed_at
                        # (DATETIME): ``julianday(maturity_date) -
                        # julianday(disbursed_at) >= 30`` — without +1, when
                        # random_int(30, 365) returns 30, the diff is
                        # ``30 - 0.766 = 29.234 < 30`` → CHECK fails.
                        target_is_date_only = _is_date_only_type(col_type)
                        source_is_datetime = (
                            column_types is not None
                            and _is_datetime_type(column_types.get(other_col_p41, ""))
                        )
                        if target_is_date_only and source_is_datetime:
                            min_days_p41 += 1
                        return {
                            "derive_from": other_col_p41,
                            "expression": f"value + timedelta(days=random_int({min_days_p41}, 365))",
                        }
                    days_p41 = "0" if op_p41 == "<=" else "1"
                    return {
                        "derive_from": other_col_p41,
                        "expression": f"value - timedelta(days=random_int({days_p41}, 365))",
                    }
                if is_float_type:
                    if op_p41 == ">=":
                        return {
                            "derive_from": other_col_p41,
                            "expression": "value + random_float(1, 100)",
                        }
                    if op_p41 == ">":
                        return {
                            "derive_from": other_col_p41,
                            "expression": "value * random_float(1.1, 2.0)",
                        }
                    if op_p41 == "<=":
                        return {
                            "derive_from": other_col_p41,
                            "expression": "value * random_float(0.5, 1.0)",
                        }
                    return {
                        "derive_from": other_col_p41,
                        "expression": "value * random_float(0.5, 0.99)",
                    }
                if op_p41 == ">=":
                    return {
                        "derive_from": other_col_p41,
                        "expression": "value + random_int(1, 100)",
                    }
                if op_p41 == ">":
                    return {
                        "derive_from": other_col_p41,
                        "expression": "value + random_int(1, 100)",
                    }
                if op_p41 == "<=":
                    return {
                        "derive_from": other_col_p41,
                        "expression": "value - random_int(0, 100)",
                    }
                return {
                    "derive_from": other_col_p41,
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

        # Pattern 6: col != other_col (inequality between two columns)
        # Handles both ``col != other_col`` and ``other_col != col`` (reversed).
        # Integer/FK variant: uses ``value - 1 if value > 1 else value + 1``
        # to guarantee inequality while staying within the valid FK range
        # (assumes sequential IDs starting from 1).
        # TEXT variant: when the column has a CHECK IN (...) constraint, builds
        # a rotation ternary that cycles through the IN set, guaranteeing the
        # result is always a different value from the set.
        # e.g., base_currency != quote_currency (both IN ('CNY','USD','EUR','HKD'))
        #   → 'USD' if value == 'CNY' else 'EUR' if value == 'USD' else ...
        other_col_p6: str | None = None
        m_p6 = re.match(rf"^\s*{col}\s*!=\s*(\w+)\s*$", expr, re.IGNORECASE)
        if m_p6:
            other_col_p6 = m_p6.group(1)
        else:
            # Reversed form: other_col != col
            m_p6_rev = re.match(rf"^\s*(\w+)\s*!=\s*{col}\s*$", expr, re.IGNORECASE)
            if m_p6_rev:
                other_col_p6 = m_p6_rev.group(1)
        if other_col_p6 and other_col_p6 in col_set and other_col_p6 != col_name:
            # Cycle prevention: only apply Pattern 6 to the column that comes
            # LATER in the column list. The constraint ``col != other_col`` is
            # symmetric — both columns match (one via direct form, the other via
            # reversed form). Without this check, both columns would derive_from
            # each other, creating a circular dependency that crashes the DAG.
            # By only applying to the later column, the earlier column is the
            # source (generated first), and the later column derives from it.
            col_idx_p6 = all_columns.index(col_name) if col_name in all_columns else -1
            other_idx_p6 = all_columns.index(other_col_p6) if other_col_p6 in all_columns else -1
            # UNIQUE-constraint guard: when col and other_col are BOTH part of
            # the same UNIQUE constraint, the deterministic expression
            # ``value - 1 if value > 1 else value + 1`` maps each other_col
            # value to exactly one col value. This limits the number of unique
            # (other_col, col) pairs to the number of distinct other_col values,
            # making large fills impossible (e.g., 1000 routes with 1000
            # warehouses — after 500 rows, collision probability is 50%).
            # Skip Pattern 6 and let the ConstraintSolver handle the ``!=``
            # constraint via retry logic with independent random FK sampling.
            p6_unique_conflict = any(
                uc.get("type") == "unique"
                and col_name in uc.get("columns", [])
                and other_col_p6 in uc.get("columns", [])
                for uc in constraints
            )
            should_apply_p6 = col_idx_p6 > other_idx_p6 and not p6_unique_conflict
            if should_apply_p6 and is_int_type:
                return {
                    "derive_from": other_col_p6,
                    "expression": "value - 1 if value > 1 else value + 1",
                }
            # TEXT columns: build a rotation ternary from the IN set.
            # Scan constraints for ``col IN ('v1', 'v2', ...)`` to extract
            # valid values, then cycle: each value maps to the next, last
            # maps to first. This guarantees result != value for any value
            # in the set.
            if should_apply_p6 and col_type.upper() in ("TEXT", "VARCHAR", "CHAR"):
                for ic in constraints:
                    if ic.get("type") != "check":
                        continue
                    ic_expr = ic.get("expression", "")
                    m_in_p6 = re.match(
                        rf"^\s*{col}\s+IN\s*\(([^)]+)\)\s*$",
                        ic_expr,
                        re.IGNORECASE,
                    )
                    if m_in_p6:
                        in_values_p6 = re.findall(r"'([^']+)'", m_in_p6.group(1))
                        if len(in_values_p6) >= 2:
                            # Build chained ternary: v1→v2, v2→v3, ..., vN→v1
                            parts_p6 = []
                            for i_p6 in range(len(in_values_p6) - 1):
                                parts_p6.append(
                                    f"'{in_values_p6[i_p6 + 1]}' if value == '{in_values_p6[i_p6]}'"
                                )
                            expr_p6 = " else ".join(parts_p6)
                            expr_p6 += f" else '{in_values_p6[0]}'"
                            return {
                                "derive_from": other_col_p6,
                                "expression": expr_p6,
                            }
                        break

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

        # Pattern 7: col >= col1 * col2 (arithmetic comparison — two columns)
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

        # Pattern 7b: col >= col2 * CONSTANT (arithmetic comparison — column times literal)
        # e.g., base_price_yearly >= base_price_monthly * 10
        # Derive from col2, multiply by CONSTANT to exactly satisfy >= (equality).
        # The constant is a numeric literal (int or float), NOT a column name.
        m = re.match(
            rf"^\s*{col}\s*>=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p7b, c_str_p7b = m.group(1), m.group(2)
            if other_col_p7b in col_set and other_col_p7b != col_name:
                c_val_p7b = float(c_str_p7b) if "." in c_str_p7b else int(c_str_p7b)
                return {
                    "derive_from": other_col_p7b,
                    "expression": f"value * {c_val_p7b}",
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

        # Pattern 11: col = col1 + col2 + col3 [+ col4 [+ ...]] (N-column addition equality, N >= 3)
        # e.g., total_amount = base_charge + weight_charge + distance_charge + fuel_surcharge + insurance_charge + tax
        # Derive from col1 (first operand), reference remaining cols via row dict.
        # The expression computes exactly col1 + col2 + ... + colN, satisfying the
        # equality constraint. Only supports + operator (most common case for
        # multi-column sums like invoices, totals, bills).
        m = re.match(
            rf"^\s*{col}\s*=\s*(\w+(?:\s*\+\s*\w+)+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            rhs = m.group(1)
            sum_cols = [c.strip() for c in rhs.split("+")]
            # Need at least 3 columns (2-column sums are handled by Pattern 10)
            if len(sum_cols) >= 3 and all(c in col_set for c in sum_cols) and sum_cols[0] != col_name:
                derive_col = sum_cols[0]
                ref_cols = sum_cols[1:]
                expr_parts = "value" + "".join(f" + row['{c}']" for c in ref_cols)
                return {
                    "derive_from": derive_col,
                    "expression": expr_parts,
                }

        # Pattern 42: col = abs(col1 - col2) (abs subtraction equality)
        # e.g., weight_diff = abs(total_weight_kg - billed_weight_kg)
        # Derive from col1, reference col2 via row dict. The expression computes
        # abs(value - row[col2]), satisfying the equality constraint.
        m = re.match(
            rf"^\s*{col}\s*=\s*abs\s*\(\s*(\w+)\s*-\s*(\w+)\s*\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1_p42, col2_p42 = m.group(1), m.group(2)
            if (col1_p42 in col_set and col2_p42 in col_set
                    and col1_p42 != col_name):
                return {
                    "derive_from": col1_p42,
                    "expression": f"abs(value - row['{col2_p42}'])",
                }

        # Pattern 43: col <= col2 * CONST1 + CONST2 (compound arithmetic upper bound)
        # e.g., estimated_hours <= distance_km * 0.5 + 24.0
        # Derive from col2, expression: value * CONST1 + random_float(0, CONST2)
        # (random offset 0..CONST2 ensures col <= col2 * CONST1 + CONST2).
        m = re.match(
            rf"^\s*{col}\s*<=\s*(\w+)\s*\*\s*(-?\d+(?:\.\d+)?)\s*\+\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col2_p43, const1_p43, const2_p43 = m.group(1), m.group(2), m.group(3)
            if col2_p43 in col_set and col2_p43 != col_name:
                return {
                    "derive_from": col2_p43,
                    "expression": f"value * {const1_p43} + random_float(0.0, {const2_p43})",
                }

        # Pattern 44: col = col1 * col2 * col3 / CONST (3-column multiplication+division)
        # e.g., expected_interest = principal * interest_rate * term_months / 12.0
        # Derive from col1, reference col2 and col3 via row dict.
        m = re.match(
            rf"^\s*{col}\s*=\s*(\w+)\s*\*\s*(\w+)\s*\*\s*(\w+)\s*/\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1_p44, col2_p44, col3_p44, divisor_p44 = m.group(1), m.group(2), m.group(3), m.group(4)
            if (col1_p44 in col_set and col2_p44 in col_set and col3_p44 in col_set
                    and col1_p44 != col_name):
                return {
                    "derive_from": col1_p44,
                    "expression": f"value * row['{col2_p44}'] * row['{col3_p44}'] / {divisor_p44}",
                }

        # Pattern 45: col = col1 + col1 * col2 * col3 / CONST (compound arithmetic with repeated column)
        # e.g., total_payable = principal + principal * interest_rate * term_months / 12.0
        # Derive from col1 (repeated), reference col2 and col3 via row dict.
        m = re.match(
            rf"^\s*{col}\s*=\s*(\w+)\s*\+\s*\1\s*\*\s*(\w+)\s*\*\s*(\w+)\s*/\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1_p45, col2_p45, col3_p45, divisor_p45 = m.group(1), m.group(2), m.group(3), m.group(4)
            if (col1_p45 in col_set and col2_p45 in col_set and col3_p45 in col_set
                    and col1_p45 != col_name):
                return {
                    "derive_from": col1_p45,
                    "expression": f"value + value * row['{col2_p45}'] * row['{col3_p45}'] / {divisor_p45}",
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
        if m:
            # First ordering: "col1 <op> col = total" → groups: (col1, op, total)
            other_col, op, total_col = m.group(1), m.group(2), m.group(3)
        else:
            # Try reverse ordering: "col <op> col1 = total"
            m = re.match(
                rf"^\s*{col}\s*([+\-])\s*(\w+)\s*=\s*(\w+)\s*$",
                expr,
                re.IGNORECASE,
            )
            if m:
                # Reverse ordering groups: (op, col1, total) — note the swap!
                op, other_col, total_col = m.group(1), m.group(2), m.group(3)
        if m:
            if other_col in col_set and total_col in col_set and total_col != col_name:
                # Cycle prevention: the constraint ``col1 + col2 = total`` is
                # symmetric — both addends match Pattern 19 (one via first
                # ordering, the other via reverse). Without this check, both
                # would derive_from total and reference each other, creating a
                # circular dependency that crashes the DAG. By only applying
                # the ``total - other`` expression to the LATER column, the
                # earlier column becomes the source (generated first).
                col_idx_p19 = all_columns.index(col_name) if col_name in all_columns else -1
                other_idx_p19 = all_columns.index(other_col) if other_col in all_columns else -1
                if col_idx_p19 > other_idx_p19:
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
                # col is the EARLIER addend. Derive it from total as an
                # integer fraction so that col ∈ [0, total] (when total >= 0).
                # This guarantees the LATER addend (total - col) is also in
                # [0, total], satisfying both ``col >= 0`` and
                # ``other_col >= 0`` CHECK constraints. Only applies to
                # addition (``col + other = total``); subtraction variants
                # (``col - other = total``) don't have the same non-negativity
                # guarantee, so we skip and let other patterns handle them.
                #
                # Uses ``random_int`` (not ``random_float``) to guarantee the
                # CHECK ``col1 + col2 = total`` holds EXACTLY in IEEE 754
                # floating point. Integers up to 2^53 are exactly representable
                # in double precision, and ``int + (float - int) = float`` is
                # exact for normal-range floats (the integer only affects the
                # integer part, leaving the fractional bits untouched). With
                # ``random_float``, the multiplication ``total * frac``
                # introduces rounding, and ``frac*total + (total - frac*total)``
                # may differ from ``total`` by 1 ULP, failing the ``=``
                # CHECK on REAL columns.
                if op == "+":
                    return {
                        "derive_from": total_col,
                        "expression": "random_int(0, max(0, int(value)))",
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
                # Build expression that produces VALUE or a compliant value.
                # Use addition/subtraction (NOT multiplication) for float comparisons —
                # multiplication reverses inequality for negative values.
                if op == ">":
                    comp_expr = "value + random_float(0.01, 100.0)" if is_float_p24 else "value + random_int(1, 100)"
                elif op == ">=":
                    comp_expr = "value + random_float(0, 100.0)" if is_float_p24 else "value + random_int(0, 100)"
                elif op == "<":
                    comp_expr = "value - random_float(0.01, 100.0)" if is_float_p24 else "value - random_int(1, 100)"
                else:  # <=
                    comp_expr = "value - random_float(0, 100.0)" if is_float_p24 else "value - random_int(0, 100)"
                return {
                    "derive_from": other_col,
                    "expression": f"{val_num_p24} if random_int(0, 1) == 0 else {comp_expr}",
                }

        # Pattern 24b: col1 != VALUE OR col (>=|>|<=|<) other_col
        # (inequality-first variant of Pattern 24 — col1 is compared with
        # inequality rather than equality)
        # e.g., status != 'paid' OR paid_amount >= total_amount
        # Semantics: when col1 == VALUE, col must satisfy the comparison
        # against other_col; otherwise col can be anything (use VALUE or a
        # safe default). Derive from other_col to ensure the comparison holds
        # when col1 == VALUE. When col1 != VALUE, use 0 (safe default).
        # 50% of the time when col1 != VALUE, use a value satisfying the
        # comparison anyway (more realistic distribution).
        m = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*(>=|>|<=|<)\s*(\w+)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            cond_col_p24b, val_str_p24b, op_p24b, other_col_p24b = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4),
            )
            if other_col_p24b in col_set and other_col_p24b != col_name and cond_col_p24b in col_set:
                # Cross-constraint cap: if there's also a ``col <= other_col``
                # or ``col < other_col`` constraint on the same column referencing
                # the same other_col, the comparison expression must NOT exceed
                # other_col. When op is >= or >, use ``value`` (exact equality)
                # to satisfy both >= and <= simultaneously.
                # e.g., ``status != 'paid' OR paid_amount >= total_amount`` +
                #       ``paid_amount <= total_amount`` → paid_amount == total_amount
                has_upper_cap = any(
                    re.match(
                        rf"^\s*{col}\s*(<=|<)\s*{other_col_p24b}\s*$",
                        c2.get("expression", ""),
                        re.IGNORECASE,
                    )
                    for c2 in constraints
                    if c2.get("type") == "check"
                )
                if has_upper_cap and op_p24b in (">=", ">"):
                    # Exact equality satisfies both >= and <= constraints
                    comp_expr_p24b = "value"
                elif op_p24b == ">":
                    # Addition (not multiplication) — see Pattern 1b pre-loop scan comment.
                    comp_expr_p24b = (
                        "value + random_float(0.01, 100.0)" if is_float_type else "value + random_int(1, 100)"
                    )
                elif op_p24b == ">=":
                    comp_expr_p24b = "value + random_float(0, 100.0)" if is_float_type else "value + random_int(0, 100)"
                elif op_p24b == "<":
                    comp_expr_p24b = (
                        "value - random_float(0.01, 100.0)" if is_float_type else "value - random_int(1, 100)"
                    )
                else:  # <=
                    comp_expr_p24b = "value - random_float(0, 100.0)" if is_float_type else "value - random_int(0, 100)"
                # Derive from other_col; reference cond_col via row dict.
                # When cond_col == VALUE: produce compliant value.
                # When cond_col != VALUE: 50% compliant, 50% safe zero.
                safe_expr = "0.0" if is_float_type else "0"
                return {
                    "derive_from": other_col_p24b,
                    "expression": (
                        f"{comp_expr_p24b} if row['{cond_col_p24b}'] == '{val_str_p24b}' "
                        f"else ({comp_expr_p24b} if random_int(0, 1) == 0 else {safe_expr})"
                    ),
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

        # Pattern 38: col = (col1 + col2) * (CONST - col3) (complex arithmetic)
        # e.g., total_amount = (base_amount + seat_amount) * (1.0 - discount_rate)
        # Derive from col1 (first operand), reference col2 and col3 via row dict.
        # The CONST and col3 are in the subtraction term (1.0 - discount_rate).
        m = re.match(
            rf"^\s*{col}\s*=\s*\(\s*(\w+)\s*\+\s*(\w+)\s*\)\s*\*\s*\(\s*(-?\d+(?:\.\d+)?)\s*-\s*(\w+)\s*\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            col1_p38, col2_p38, const_p38, col3_p38 = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4),
            )
            if col1_p38 in col_set and col2_p38 in col_set and col3_p38 in col_set and col1_p38 != col_name:
                return {
                    "derive_from": col1_p38,
                    "expression": f"(value + row['{col2_p38}']) * ({const_p38} - row['{col3_p38}'])",
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

        # Pattern 26b: col1 != VALUE OR col IN ('a', 'b', 'c')
        # (inequality-first variant of Pattern 26 — col1 is compared with
        # inequality rather than equality)
        # e.g., scope != 'global' OR action IN ('admin', 'read')
        # Semantics: when col1 == VALUE, col must be in the enum set;
        # otherwise col can be anything. Derive from col1: when col1 == VALUE,
        # pick a random value from the set; otherwise pick the first set
        # value (safe default). The expression references the parsed set
        # via random_choice-style selection.
        m = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s+IN\s*\(([^)]+)\)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            cond_col_p26b, val_str_p26b, values_str_p26b = (
                m.group(1),
                m.group(2),
                m.group(3),
            )
            if cond_col_p26b in col_set and cond_col_p26b != col_name:
                # Parse the values: 'a', 'b', 'c' → ['a', 'b', 'c']
                values_p26b = re.findall(r"'([^']*)'", values_str_p26b)
                if not values_p26b:
                    values_p26b = re.findall(r'"([^"]*)"', values_str_p26b)
                if values_p26b:
                    py_list_p26b = "[" + ", ".join(f"'{v}'" for v in values_p26b) + "]"
                    first_val_p26b = values_p26b[0]
                    # When cond_col == VALUE: pick from the set (satisfies IN).
                    # When cond_col != VALUE: use first set value (safe default).
                    return {
                        "derive_from": cond_col_p26b,
                        "expression": (
                            f"{py_list_p26b}[random_int(0, {len(values_p26b) - 1})] "
                            f"if value == '{val_str_p26b}' else '{first_val_p26b}'"
                        ),
                    }

        # Pattern 26c: col1 != VALUE OR col = 'V1' OR col = 'V2' [OR col = 'V3' ...]
        # (explicit OR-equality variant of Pattern 26b — instead of IN(), the
        # CHECK uses ``col = 'V1' OR col = 'V2'`` syntax)
        # e.g., scope != 'global' OR action = 'admin' OR action = 'read'
        # Semantics: when col1 == VALUE, col must be one of V1, V2, ...;
        # otherwise col can be anything. Derive from col1: when col1 == VALUE,
        # pick a random value from the set; otherwise pick the first set value.
        m = re.match(
            rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*=\s*'([^']+)'\s*(?:OR\s+{col}\s*=\s*'([^']+)'\s*)+\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            cond_col_p26c = m.group(1)
            val_str_p26c = m.group(2)
            if cond_col_p26c in col_set and cond_col_p26c != col_name:
                # Extract all quoted values after the OR keywords
                all_values_p26c = re.findall(rf"{col}\s*=\s*'([^']+)'", expr, re.IGNORECASE)
                if all_values_p26c:
                    py_list_p26c = "[" + ", ".join(f"'{v}'" for v in all_values_p26c) + "]"
                    first_val_p26c = all_values_p26c[0]
                    return {
                        "derive_from": cond_col_p26c,
                        "expression": (
                            f"{py_list_p26c}[random_int(0, {len(all_values_p26c) - 1})] "
                            f"if value == '{val_str_p26c}' else '{first_val_p26c}'"
                        ),
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
                        rand_e = f"random_float({lo}, {up})" if is_float_type else f"random_int({int(lo)}, {int(up)})"
                        parts_p36.append(f"{rand_e} if value == '{vi}'")
                    # Last clause is the fallback
                    _oc, _vi, lo_op, lo_str, up_op, up_str = clauses_36[-1]
                    lo = float(lo_str)
                    up = float(up_str)
                    if lo_op == ">":
                        lo += 0.01 if is_float_type else 1
                    if up_op == "<":
                        up -= 0.01 if is_float_type else 1
                    last_rand_36 = f"random_float({lo}, {up})" if is_float_type else f"random_int({int(lo)}, {int(up)})"
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

        # Pattern 37 string variant: multiple ``col1 != VALUE_i OR col = 'VALUE2_i'``
        # on same column (multi-conditional cross-column with string equality).
        # When 2+ separate CHECK constraints constrain the SAME target column
        # to a specific STRING value based on the SAME enum column's value,
        # derive col from the enum column with a nested ternary mapping each
        # enum value to its required string.
        # e.g., R6.transactions.direction has:
        #   CHECK (txn_type != 'withdrawal' OR direction = 'out')
        #   CHECK (txn_type != 'deposit' OR direction = 'in')
        #   CHECK (txn_type != 'fee' OR direction = 'out')
        #   CHECK (txn_type != 'interest' OR direction = 'in')
        # Derive from txn_type: 'out' if withdrawal, 'in' if deposit, etc.
        # Default branch: pick the first VALUE2 (guaranteed valid for any
        # enum value not explicitly listed).
        p37s_branches: list[tuple[str, str]] = []
        p37s_other_col: str | None = None
        for c_p37s in constraints:
            if c_p37s.get("type") != "check":
                continue
            expr_p37s = c_p37s.get("expression", "")
            if not expr_p37s:
                continue
            m_p37s = re.match(
                rf"^\s*(\w+)\s*!=\s*'([^']+)'\s+OR\s+{col}\s*=\s*'([^']*)'\s*$",
                expr_p37s,
                re.IGNORECASE,
            )
            if not m_p37s:
                continue
            other_p37s, val_p37s, eq_val_p37s = (
                m_p37s.group(1),
                m_p37s.group(2),
                m_p37s.group(3),
            )
            if other_p37s not in col_set or other_p37s == col_name:
                continue
            if p37s_other_col is None:
                p37s_other_col = other_p37s
            elif p37s_other_col != other_p37s:
                continue
            p37s_branches.append((val_p37s, eq_val_p37s))
        if p37s_other_col is not None and len(p37s_branches) >= 2:
            # Build nested ternary: 'V2_1' if value == 'V1' else ('V2_2' if value == 'V2' else (... else default))
            default_p37s = f"'{p37s_branches[0][1]}'"
            expr_p37s_final = default_p37s
            for val_p37s, eq_val_p37s in reversed(p37s_branches):
                expr_p37s_final = f"'{eq_val_p37s}' if value == '{val_p37s}' else ({expr_p37s_final})"
            return {
                "derive_from": p37s_other_col,
                "expression": expr_p37s_final,
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

        # Pattern 46: col = INT_VALUE OR other_col (<|<=) CONST [OR ...]
        # (multi-clause disjunction with integer equality as first clause)
        # e.g., is_free = 1 OR price < 100 OR original_price IS NULL OR original_price < 200
        # Semantics: the CHECK is satisfied if ANY clause is true. When
        # other_col violates the inequality (>= CONST for <, > CONST for <=),
        # col MUST be INT_VALUE to satisfy the first clause. When other_col
        # satisfies the inequality, col can be any valid value (the second
        # clause is already true). Derive from other_col: set col to INT_VALUE
        # when the inequality would fail, else random_int(0, INT_VALUE).
        # This is a conservative approach — setting col = INT_VALUE is always
        # safe because it satisfies the first clause regardless of other cols.
        m = re.match(
            rf"^\s*{col}\s*=\s*(\d+)\s+OR\s+(\w+)\s*(<|<=)\s*(-?\d+(?:\.\d+)?)\s*(?:OR\s+.*)?$",
            expr,
            re.IGNORECASE,
        )
        if m:
            val_p46 = int(m.group(1))
            other_col_p46 = m.group(2)
            op_p46 = m.group(3)
            threshold_p46 = float(m.group(4))
            if other_col_p46 in col_set and other_col_p46 != col_name:
                # When other_col violates the inequality, col MUST be INT_VALUE.
                violate_expr = f"value >= {threshold_p46}" if op_p46 == "<" else f"value > {threshold_p46}"
                return {
                    "derive_from": other_col_p46,
                    "expression": f"{val_p46} if {violate_expr} else random_int(0, {val_p46})",
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
                            positive_expr = f"min({positive_expr}, row['{upper_col_p28}'])"
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

        # Pattern 30b: col1 = VALUE OR col IS NOT NULL (reverse of Pattern 30 —
        # when col1 == VALUE, col can be anything including NULL; when col1 !=
        # VALUE, col must be NOT NULL)
        # e.g., org_type = 'root' OR parent_id IS NOT NULL
        # Derive from col1: when col1 == VALUE, set col to None (NULL is allowed);
        # when col1 != VALUE, set col to a safe non-NULL value. For FK columns,
        # use ``1`` (the first autoincrement id, valid after the first row is
        # inserted). For non-FK columns, use ``0`` (int) or ``0.0`` (float).
        # NOTE: this pattern often coexists with Pattern 30 on the same column
        # (e.g., ``org_type != 'root' OR parent_id IS NULL`` + ``org_type =
        # 'root' OR parent_id IS NOT NULL``), which together mean: parent_id is
        # NULL iff org_type == 'root'. Pattern 30 runs first and returns
        # ``None if value == 'root' else None`` for FK columns (always NULL).
        # Pattern 30b overrides this for the non-VALUE branch to be non-NULL.
        # However, since Pattern 30 already returned, Pattern 30b only fires
        # when Pattern 30 did NOT match (i.e., the CHECK uses ``= VALUE``
        # instead of ``!= VALUE``).
        m = re.match(
            rf"^\s*(\w+)\s*=\s*'([^']+)'\s+OR\s+{col}\s+IS\s+NOT\s+NULL\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p30b, val_str_p30b = m.group(1), m.group(2)
            if other_col_p30b in col_set and other_col_p30b != col_name:
                # When col1 == VALUE: col = None (NULL is allowed)
                # When col1 != VALUE: col = non-NULL
                # For FK columns: use 1 (first autoincrement id, valid after first row)
                # For non-FK columns: use 0 (int) or 0.0 (float)
                non_null_expr_p30b = "1" if is_fk_column else ("0.0" if is_float_type else "0")
                return {
                    "derive_from": other_col_p30b,
                    "expression": f"None if value == '{val_str_p30b}' else {non_null_expr_p30b}",
                }

        # Pattern 30b (int variant): col1 = INTEGER_VALUE OR col IS NOT NULL
        # e.g., level = 1 OR parent_id IS NOT NULL
        # Same semantics as the string variant but with an unquoted integer VALUE.
        # When col1 == INT_VALUE: col = None (NULL is allowed);
        # when col1 != INT_VALUE: col = non-NULL (1 for FK, 0/0.0 for others).
        m_int_p30b = re.match(
            rf"^\s*(\w+)\s*=\s*(\d+)\s+OR\s+{col}\s+IS\s+NOT\s+NULL\s*$",
            expr,
            re.IGNORECASE,
        )
        if m_int_p30b:
            other_col_p30b_int, val_int_p30b = m_int_p30b.group(1), m_int_p30b.group(2)
            if other_col_p30b_int in col_set and other_col_p30b_int != col_name:
                non_null_expr_p30b_int = "1" if is_fk_column else ("0.0" if is_float_type else "0")
                return {
                    "derive_from": other_col_p30b_int,
                    "expression": f"None if value == {val_int_p30b} else {non_null_expr_p30b_int}",
                }

        # Pattern 30b (NOT IN variant): col1 NOT IN ('v1','v2',...) OR col IS NOT NULL
        # (when col1 IS in the set, col must be NOT NULL; when col1 is NOT in
        # the set, col can be NULL). This is the multi-value variant of
        # Pattern 30b (which handles ``col1 = 'VALUE' OR col IS NOT NULL``).
        # e.g., status NOT IN ('approved', 'settled') OR approved_amount IS NOT NULL
        # Derive from col1: when col1 NOT IN the set, set col to None (NULL
        # allowed); when col1 IN the set, set col to a safe non-NULL value.
        # For FK columns, use ``1`` (first autoincrement id). For float
        # columns, use ``random_float(0.01, 1000.0)`` (positive, satisfies
        # ``> 0.0`` CHECKs). For int columns, use ``random_int(1, 1000)``.
        m_notin_p30b = re.match(
            rf"^\s*(\w+)\s+NOT\s+IN\s*\(([^)]+)\)\s+OR\s+{col}\s+IS\s+NOT\s+NULL\s*$",
            expr,
            re.IGNORECASE,
        )
        if m_notin_p30b:
            other_col_p30b_notin = m_notin_p30b.group(1)
            values_str_p30b_notin = m_notin_p30b.group(2)
            if other_col_p30b_notin in col_set and other_col_p30b_notin != col_name:
                # Parse the value list: 'v1', 'v2', ...
                values_p30b_notin = re.findall(r"'([^']*)'", values_str_p30b_notin)
                values_repr_p30b_notin = ", ".join(f"'{v}'" for v in values_p30b_notin)
                if is_fk_column:
                    non_null_expr_p30b_notin = "1"
                elif is_float_type:
                    non_null_expr_p30b_notin = "random_float(0.01, 1000.0)"
                elif "INT" in col_type.upper():
                    non_null_expr_p30b_notin = "random_int(1, 1000)"
                else:
                    non_null_expr_p30b_notin = "'0'"
                return {
                    "derive_from": other_col_p30b_notin,
                    "expression": f"None if value not in ({values_repr_p30b_notin}) else {non_null_expr_p30b_notin}",
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
        # RANGE AWARENESS: if the column also has a range CHECK constraint
        # (e.g., ``col >= 0.0 AND col <= 1.0``), the random branch must
        # respect those bounds instead of the hardcoded [0.01, 100.0].
        # This prevents CHECK violations when the column's allowed range is
        # narrower than the default. e.g., discount_rate has range [0.0, 1.0]
        # and Pattern 31 constraint ``status != 'trialing' OR discount_rate = 0.0``;
        # the else branch must use random_float(0.01, 1.0), not 100.0.
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
                # Scan all constraints for a range CHECK on this column:
                # ``col >= X AND col <= Y`` or ``col >= X`` / ``col <= Y`` (separate)
                range_min: float | None = None
                range_max: float | None = None
                for rc in constraints:
                    if rc.get("type") != "check":
                        continue
                    rc_expr = rc.get("expression", "")
                    # Combined: col >= X AND col <= Y
                    m_combined = re.match(
                        rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$",
                        rc_expr,
                        re.IGNORECASE,
                    )
                    if m_combined:
                        range_min = float(m_combined.group(1))
                        range_max = float(m_combined.group(2))
                        break
                    # Separate lower: col >= X
                    m_low = re.match(rf"^\s*{col}\s*>=\s*(-?\d+(?:\.\d+)?)\s*$", rc_expr, re.IGNORECASE)
                    if m_low:
                        range_min = float(m_low.group(1))
                    # Separate upper: col <= Y
                    m_up = re.match(rf"^\s*{col}\s*<=\s*(-?\d+(?:\.\d+)?)\s*$", rc_expr, re.IGNORECASE)
                    if m_up:
                        range_max = float(m_up.group(1))
                # Build rand_expr using range bounds if available
                if is_float_p31:
                    lo = max(0.01, range_min) if range_min is not None else 0.01
                    hi = min(100.0, range_max) if range_max is not None else 100.0
                    if lo > hi:
                        lo, hi = hi, lo
                    rand_expr = f"random_float({lo}, {hi})"
                else:
                    lo_i = max(1, int(range_min)) if range_min is not None else 1
                    hi_i = min(100, int(range_max)) if range_max is not None else 100
                    if lo_i > hi_i:
                        lo_i, hi_i = hi_i, lo_i
                    rand_expr = f"random_int({lo_i}, {hi_i})"
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

        # Pattern 34b: col1 != INTEGER_VALUE OR col (<|<=) X
        # (integer-value variant of Pattern 34 — VALUE is an unquoted integer)
        # e.g., is_system != 1 OR priority < 100
        # Same semantics as Pattern 34: set max_value to X - epsilon
        # (exclusive) or X (inclusive) unconditionally. Preserves single-column
        # lower bound via _infer_from_check_constraints.
        m = re.match(
            rf"^\s*(\w+)\s*!=\s*(-?\d+)\s+OR\s+{col}\s*(<|<=)\s*(-?\d+(?:\.\d+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p34b, _val_str_p34b, op_p34b, x_str_p34b = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4),
            )
            if other_col_p34b in col_set and other_col_p34b != col_name:
                is_float_p34b = "." in x_str_p34b
                x_val_p34b = float(x_str_p34b)
                single_p34b = _infer_from_check_constraints(col_name, constraints, all_columns)
                if op_p34b == "<":
                    if is_float_p34b:
                        params_p34b: dict[str, Any] = {"max_value": x_val_p34b - 0.01}
                        gen_p34b = "float"
                    else:
                        params_p34b = {"max_value": int(x_val_p34b) - 1}
                        gen_p34b = "integer"
                elif is_float_p34b:
                    params_p34b = {"max_value": x_val_p34b}
                    gen_p34b = "float"
                else:
                    params_p34b = {"max_value": int(x_val_p34b)}
                    gen_p34b = "integer"
                if single_p34b and single_p34b[1].get("min_value") is not None:
                    params_p34b["min_value"] = single_p34b[1]["min_value"]
                return {"generator": gen_p34b, "params": params_p34b}

        # Pattern 28b: col1 != INTEGER_VALUE OR col > X
        # (integer-value variant of Pattern 28 — VALUE is an unquoted integer)
        # e.g., is_approved != 1 OR approved_count > 0
        # Same semantics as Pattern 28: derive from col1; when col1 == VALUE,
        # produce a value > threshold; otherwise produce 0.
        m = re.match(
            rf"^\s*(\w+)\s*!=\s*(-?\d+)\s+OR\s+{col}\s*>\s*(-?[0-9]+(?:\.[0-9]+)?)\s*$",
            expr,
            re.IGNORECASE,
        )
        if m:
            other_col_p28b, val_str_p28b, threshold_str_p28b = (
                m.group(1),
                m.group(2),
                m.group(3),
            )
            if other_col_p28b in col_set and other_col_p28b != col_name:
                threshold_p28b = float(threshold_str_p28b)
                val_int_p28b = int(val_str_p28b)
                positive_expr_p28b = f"random_float({threshold_p28b + 0.01}, {threshold_p28b + 100.0})"
                zero_expr_p28b = "0.0" if is_float_type else "0"
                return {
                    "derive_from": other_col_p28b,
                    "expression": (f"{positive_expr_p28b} if value == {val_int_p28b} else {zero_expr_p28b}"),
                }

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
