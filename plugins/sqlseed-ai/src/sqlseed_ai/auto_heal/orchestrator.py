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

from typing import TYPE_CHECKING, Any

import yaml
from sqlseed_ai.auto_heal.time_budget import TimeBudgetController
from sqlseed_ai.healer.post_repair import BrokenEdgeAligner
from sqlseed_ai.healer.subgraph import SubgraphSplitter
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.healer.coordinator import Layer4Coordinator

logger = get_logger(__name__)


class AutoHealOrchestrator:
    """Top-level orchestrator for the contract-driven self-healing pipeline."""

    def __init__(
        self,
        *,
        db_path: str | None = None,
        url: str | None = None,
        healer: Any,  # LLMHealer
        validator: Any,  # FastValidator
        total_budget_seconds: float = 300.0,
        max_scc_size: int = 3,
    ) -> None:
        self._db_path = db_path
        self._url = url
        self._healer = healer
        self._validator = validator
        self._total_budget = total_budget_seconds
        self._max_scc_size = max_scc_size

    def run(
        self,
        *,
        broken_edges_inject: list[tuple[str, str]] | None = None,
    ) -> str:
        """Execute the full pipeline and return the final YAML config string."""
        # Step 1: snapshot (Defense 8)
        snapshot = SchemaSnapshot(db_path=self._db_path, url=self._url)
        original_hash = snapshot.schema_hash

        # Step 2: subgraph splitting (Defenses 2 + 6)
        splitter = SubgraphSplitter(max_scc_size=self._max_scc_size)
        fk_graph = self._build_fk_graph(snapshot)
        subgraphs, broken_edges = splitter.split(fk_graph)
        if broken_edges_inject:
            broken_edges.extend(broken_edges_inject)

        # Time budget
        budget = TimeBudgetController(
            total_seconds=self._total_budget,
            table_count=len(snapshot.tables),
        )

        # Step 3: per-subgraph validate → repair → heal
        config: dict[str, Any] = {"tables": []}
        for sg_tables in subgraphs:
            if budget.is_expired():
                logger.warning(
                    "Time budget expired, falling back to defaults",
                    remaining_tables=sg_tables,
                )
                self._append_default_columns(config, sg_tables, snapshot)
                continue

            sg_config = self._build_subgraph_config(sg_tables, snapshot)
            violations = self._validate(sg_config, snapshot)
            if not violations:
                config["tables"].extend(sg_config["tables"])
                continue
            # Layer 3 + Layer 4: repair + heal
            result = self._heal_subgraph(sg_config, sg_tables, violations, snapshot, original_hash, budget)
            config["tables"].extend(result.get("tables", []))

        # Step 4: post-repair broken edges (Section 14)
        if broken_edges:
            aligner = BrokenEdgeAligner()
            config = aligner.align(config, broken_edges)

        # Step 5: Defense 8 optimistic lock — verify schema unchanged
        new_snapshot = SchemaSnapshot(db_path=self._db_path, url=self._url)
        if new_snapshot.schema_hash != original_hash:
            logger.error(
                "Defense 8: schema drift detected, aborting YAML write",
                original=original_hash,
                current=new_snapshot.schema_hash,
            )
            raise RuntimeError(f"Schema changed during auto-heal: {original_hash} -> {new_snapshot.schema_hash}")

        # Step 6: emit YAML
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
        """Build initial config for a subgraph (placeholder generators).

        Note: placeholders are type-based and do NOT account for
        UNIQUE/FK/CHECK constraints. Constraint enforcement is deferred
        to Layer 3 (RepairPipeline) and Layer 4 (LLM healer).
        """
        logger.warning(
            "Subgraph initial config uses type-based placeholders; "
            "UNIQUE/FK/CHECK constraints will be enforced by Layer 3/4",
            tables=tables,
        )
        sg_config: dict[str, Any] = {"tables": []}
        for table_name in tables:
            meta = snapshot.tables.get(table_name)
            if meta is None:
                continue
            cols: list[dict[str, Any]] = []
            for col_name in meta.columns:
                col_type = meta.column_types.get(col_name, "TEXT")
                cols.append(
                    {
                        "name": col_name,
                        "generator": _placeholder_generator(col_type),
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
                return sg_config  # Layer 3 fixed everything
            # Carry over remaining violations for Layer 4.
            violations = remaining
        except ImportError as e:
            logger.warning(
                "Layer 3 repair unavailable, proceeding to Layer 4",
                error=str(e),
            )

        # Layer 4: LLM healing (expensive)
        from sqlseed_ai.healer.coordinator import Layer4Coordinator
        from sqlseed_ai.healer.models import SubgraphTask

        task = SubgraphTask(
            task_id=f"sg_{sg_tables[0] if sg_tables else 'empty'}",
            tables=sg_tables,
            is_scc=len(sg_tables) > 1,
        )
        coord: Layer4Coordinator = Layer4Coordinator(
            healer=self._healer,
            validator=self._validator,
            snapshot=snapshot,
            max_attempts=3,
            schema_hash=schema_hash,
            time_budget_seconds=budget.per_table_budget(),
        )
        # Layer4Coordinator.reconcile returns HealResult with .config
        result = coord.reconcile(task, sg_config, violations)
        return result.config


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
