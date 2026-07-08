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
from typing import Any

import yaml
from sqlseed_ai.auto_heal.time_budget import TimeBudgetController
from sqlseed_ai.healer.post_repair import BrokenEdgeAligner
from sqlseed_ai.healer.subgraph import SubgraphSplitter
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


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
        collisions). Falls back to type-based placeholders for unconstrained
        columns. FK constraints are still deferred to Layer 3/4.
        """
        sg_config: dict[str, Any] = {"tables": []}
        for table_name in tables:
            meta = snapshot.tables.get(table_name)
            if meta is None:
                continue
            unique_cols = _get_unique_columns(meta.constraints)
            cols: list[dict[str, Any]] = []
            for col_name in meta.columns:
                col_type = meta.column_types.get(col_name, "TEXT")
                # Step 1: Try cross-column CHECK inference FIRST.
                # Cross-column constraints (e.g., ``unit_price > cost_price``)
                # are stronger than single-column constraints (e.g.,
                # ``unit_price > 0``) and must take priority: if the column
                # has both, derive_from captures the cross-column relation
                # while a bare min_value would silently drop it.
                cross_config = _infer_cross_column_config(col_name, meta.constraints, meta.columns, col_type)
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
                # Step 4: Fallback to type-based placeholder.
                # For TEXT columns with date-like names (created_at, check_in,
                # etc.), use ``datetime`` instead of ``string`` so that
                # date-comparison CHECKs (check_out > check_in) work correctly
                # and derive_from expressions can use timedelta.
                placeholder_gen = _placeholder_generator(col_type)
                if placeholder_gen == "string" and _is_date_column(col_name):
                    placeholder_gen = "datetime"
                cols.append(
                    {
                        "name": col_name,
                        "generator": placeholder_gen,
                        "params": {},
                    }
                )
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
    """
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
            other_cols = [c for c in all_columns if c != col_name]
            is_cross_column = False
            for other in other_cols:
                if re.search(rf"\b{re.escape(other)}\b", expr, re.IGNORECASE):
                    is_cross_column = True
                    break
            if is_cross_column:
                continue
        # Try to parse as single-column CHECK
        result = _parse_single_column_check(col_name, expr)
        if result is not None:
            return result
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
    - ``col IN ('a', 'b', 'c')`` → choice generator (string enum)
    - ``col IN (0, 1)`` → boolean generator
    - ``col IN (1, 2, 3)`` → choice generator (numeric enum)
    - ``col BETWEEN X AND Y`` → integer/float with inclusive bounds
    - ``col >= X AND col <= Y`` → inclusive range
    - ``col > X AND col < Y`` → exclusive range
    - ``col > X AND col <= Y`` / ``col >= X AND col < Y`` → mixed range
    - ``col >= X`` / ``col > X`` → lower bound only
    - ``col <= Y`` / ``col < Y`` → upper bound only
    """
    col = re.escape(col_name)

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
        rf"^\s*{col}\s+BETWEEN\s+(\d+(?:\.\d+)?)\s+AND\s+(\d+(?:\.\d+)?)\s*$",
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
        rf"^\s*{col}\s*>=\s*(\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(\d+(?:\.\d+)?)\s*$",
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

    # Pattern: col > X AND col < Y — exclusive range
    m = re.match(
        rf"^\s*{col}\s*>\s*(\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        min_str, max_str = m.group(1), m.group(2)
        is_int = "." not in min_str and "." not in max_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(min_str) + 1, "max_value": int(max_str) - 1})
        return (gen, {"min_value": float(min_str), "max_value": float(max_str)})

    # Pattern: col > X AND col <= Y — mixed range (exclusive lower, inclusive upper)
    # e.g., interest_rate > 0 AND interest_rate <= 0.3
    # For integers: shift min up by 1 (X+1) to satisfy strict inequality.
    # For floats: keep X as min_value (probability of generating exactly X is
    # effectively zero for continuous floats; if it occurs, ConstraintSolver
    # retries handle it).
    m = re.match(
        rf"^\s*{col}\s*>\s*(\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        min_str, max_str = m.group(1), m.group(2)
        is_int = "." not in min_str and "." not in max_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(min_str) + 1, "max_value": int(max_str)})
        return (gen, {"min_value": float(min_str), "max_value": float(max_str)})

    # Pattern: col >= X AND col < Y — mixed range (inclusive lower, exclusive upper)
    # e.g., score >= 0 AND score < 100
    # For integers: shift max down by 1 (Y-1) to satisfy strict inequality.
    m = re.match(
        rf"^\s*{col}\s*>=\s*(\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        min_str, max_str = m.group(1), m.group(2)
        is_int = "." not in min_str and "." not in max_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(min_str), "max_value": int(max_str) - 1})
        return (gen, {"min_value": float(min_str), "max_value": float(max_str)})

    # Pattern: col >= X — lower bound only (inclusive)
    m = re.match(
        rf"^\s*{col}\s*>=\s*(\d+(?:\.\d+)?)\s*$",
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
        rf"^\s*{col}\s*>\s*(\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"min_value": int(val_str) + 1})
        return (gen, {"min_value": float(val_str)})

    # Pattern: col <= Y — upper bound only (inclusive)
    m = re.match(
        rf"^\s*{col}\s*<=\s*(\d+(?:\.\d+)?)\s*$",
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
        rf"^\s*{col}\s*<\s*(\d+(?:\.\d+)?)\s*$",
        expr,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        is_int = "." not in val_str
        gen = "integer" if is_int else "float"
        if is_int:
            return (gen, {"max_value": int(val_str) - 1})
        return (gen, {"max_value": float(val_str)})

    return None


def _infer_cross_column_config(
    col_name: str,
    constraints: list[dict[str, Any]],
    all_columns: list[str],
    col_type: str,
) -> dict[str, Any] | None:
    """Infer config from cross-column CHECK constraints.

    Returns a config dict with either:
    - ``derive_from`` + ``expression`` (for derived mode — date/numeric ordering)
    - ``generator`` + ``params`` + ``null_ratio`` (for source mode — always NULL)

    Or ``None`` if no inference is possible.

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
    - ``col >= X AND col <= other`` (compound — literal lower + column upper)
    - ``col >= other AND col <= Y`` (compound — column lower + literal upper)
    - ``col > X AND col < other`` (compound — exclusive literal lower + exclusive column upper)
    - ``col > other AND col < Y`` (compound — exclusive column lower + exclusive literal upper)

    Skipped patterns (not safely inferable from CHECK alone):
    - ``col != other`` for non-integer columns (needs FK pool awareness)
    """
    col = re.escape(col_name)
    col_set = set(all_columns)
    is_date_type = any(k in col_type.upper() for k in ("DATE", "TIME", "DATETIME"))
    # SQLite stores dates as TEXT, so also check column name patterns.
    is_date_col = is_date_type or _is_date_column(col_name)
    is_float_type = any(k in col_type.upper() for k in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC"))
    is_int_type = any(k in col_type.upper() for k in ("INT", "BIGINT", "SMALLINT", "TINYINT"))

    for c in constraints:
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

        # Pattern 1: col IS NULL OR col (>=|>) other_col (date ordering with NULL escape)
        # Also handles: col IS NULL OR other IS NULL OR col >= other
        # e.g., termination_date IS NULL OR termination_date >= hire_date
        # e.g., due_date IS NULL OR start_date IS NULL OR due_date >= start_date
        # e.g., closed_at IS NULL OR closed_at > opened_at (strict inequality)
        # Both >= and > are handled: the derived expression adds a positive
        # timedelta (>= 1 day), which guarantees strict inequality (> source)
        # in both cases. For >=, equality is also acceptable but the timedelta
        # still satisfies it.
        m = re.search(
            rf"{col}\s+IS\s+NULL.*OR\s+{col}\s*(>=|>)\s*(\w+)",
            expr,
            re.IGNORECASE,
        )
        if m and is_date_col:
            other_col = m.group(2)
            if other_col in col_set and other_col != col_name:
                return {
                    "derive_from": other_col,
                    "expression": "value + timedelta(days=random_int(1, 365))",
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
        # e.g., remaining_balance <= loan_amount
        # For date columns: subtract a non-negative timedelta (0 days = equality).
        # For float columns (positive values): multiply by factor in [0.5, 1.0]
        #   (factor=1.0 gives equality, satisfying <=).
        # For int columns: subtract a non-negative offset (0 = equality).
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
                    "expression": "value - random_int(0, 100)",
                }

        # Pattern 8a: col >= X AND col <= other_col (compound — lower bound literal + upper bound column)
        # e.g., remaining_balance >= 0 AND remaining_balance <= loan_amount
        # Derive from other_col, generate a value in [X, other_col] using
        # random_float/random_int with the literal X as min and the derived
        # value (other_col) as max. This guarantees both bounds are satisfied
        # when other_col >= X (typically ensured by other CHECK constraints
        # like loan_amount > 0).
        m = re.match(
            rf"^\s*{col}\s*>=\s*(\d+(?:\.\d+)?)\s+AND\s+{col}\s*<=\s*(\w+)\s*$",
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
            rf"^\s*{col}\s*>=\s*(\w+)\s+AND\s+{col}\s*<=\s*(\d+(?:\.\d+)?)\s*$",
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
            rf"^\s*{col}\s*>\s*(\d+(?:\.\d+)?)\s+AND\s+{col}\s*<\s*(\w+)\s*$",
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
            rf"^\s*{col}\s*>\s*(\w+)\s+AND\s+{col}\s*<\s*(\d+(?:\.\d+)?)\s*$",
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

    return None
