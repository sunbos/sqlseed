"""Layer 3: Staged LLM analysis pipeline.

Implements the Least-to-Most Prompting approach (Zhou et al. 2022):
  Stage 0 (optional): data sampling
  Stage 1: structure analysis (1 LLM call)
  Decision: dynamic granularity selection (no LLM)
  Stage 2: column analysis (N LLM calls, granularity-adaptive)
  Stage 3: validation + auto-fix (no LLM, pure rules)

This module contains:
  - StructureSummary / TableStructureSummary dataclasses (spec §6.7)
  - StagedSchemaAnalyzer class (spec §6.6, flag-switched entry point)
  - Stage3Validator class (spec §6.1 stage 3, new auto-fix rules #14-#16)
  - ErrorClassifier class (spec §6.8)

Spec reference: docs/superpowers/specs/2026-07-02-llm-staged-yaml-analysis-design.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.config import AIConfig
    from sqlseed_ai.schema_analyzer import SchemaSemanticAnalyzer

    from sqlseed.core.features import StructuralFeatures

logger = get_logger(__name__)


# ── Spec §6.7: inter-stage data format ────────────────────────────────


@dataclass
class TableStructureSummary:
    """Single-table structure summary, Stage 1 output, Stage 2 input."""

    name: str
    purpose: str  # LLM-inferred table purpose (e.g., "employee payroll")
    anchor_columns: list[str]  # PK + UNIQUE columns (decide generation strategy)
    naming_prefix: str  # Prefix (e.g., "EMP-" for employees, derived from table name)
    complexity: int  # Score: column_count * constraint_count
    cross_column_checks: list[dict[str, Any]] = field(default_factory=list)
    # Cross-column CHECK expressions + involved column names+types
    # for per_column mode context injection.
    # Example: [{"expression": "end_date >= start_date",
    #           "columns": {"start_date": "DATE", "end_date": "DATE"}}]
    fk_references: list[dict[str, Any]] = field(default_factory=list)
    # Same-table FK reference info (this table as parent, referenced columns)
    # Example: [{"column": "id", "ref_count": 3}]


@dataclass
class StructureSummary:
    """Stage 1 complete output, passed in-memory to Stage 2/3.

    This is the "YAML state machine" Stage 1 state. Not written to disk
    unless --cache-analysis is set.
    """

    schema_hash: str  # Cache key
    topological_order: list[str]  # Table fill order (topological sort)
    fk_graph: list[dict[str, Any]]  # FK dependency graph [{parent, child, col, on_delete}]
    tables: list[TableStructureSummary]  # Per-table structure summaries
    naming_conventions: dict[str, str]  # {table_name: prefix}
    complexity_score: dict[str, Any]  # {tables, avg_columns, avg_constraints}
    dialect: str  # sqlite | postgresql


# ── Spec §6.8: error classifier ──────────────────────────────────────


class ErrorCategory(Enum):
    """LLM call failure category."""

    TRANSIENT = "transient"  # Temporary (retry may fix)
    LOGIC = "logic"  # Logic error (switch prompt/strategy)
    QUALITY = "quality"  # Insufficient quality (degrade)


class ErrorClassifier:
    """LLM call failure classifier, pure rules, no LLM.

    Spec §6.8: classify based on exception type + output content.
    """

    @staticmethod
    def classify(error: Exception, output: str | None = None) -> ErrorCategory:
        """Classify based on exception type + output content."""
        # === TRANSIENT (temporary, retry may fix) ===
        if isinstance(error, TimeoutError):
            return ErrorCategory.TRANSIENT
        try:
            from openai import APIConnectionError, APITimeoutError

            if isinstance(error, (APIConnectionError, APITimeoutError)):
                return ErrorCategory.TRANSIENT
        except ImportError:
            pass
        try:
            from openai import InternalServerError, RateLimitError

            if isinstance(error, (InternalServerError, RateLimitError)):
                return ErrorCategory.TRANSIENT
        except ImportError:
            pass
        if "out of memory" in str(error).lower() or "cuda" in str(error).lower():
            return ErrorCategory.TRANSIENT

        # === QUALITY: string-ratio check runs BEFORE the LOGIC "valid JSON dict
        # with columns" heuristic below, because a high string-generator ratio is
        # a more specific signal (LLM gave up and defaulted everything to string)
        # than the structural LOGIC tag. Spec §6.8. Regex tolerates optional
        # whitespace after the colon (both "generator":"string" and
        # "generator": "string" are valid JSON serializations).
        if output:
            gen_matches = re.findall(r'"generator"\s*:\s*"([^"]+)"', output.lower())
            if gen_matches:
                string_count = sum(1 for m in gen_matches if m == "string")
                if string_count / len(gen_matches) > 0.8:
                    return ErrorCategory.QUALITY

        # === LOGIC (logic error, switch prompt/strategy retry) ===
        if isinstance(error, (ValueError, json.JSONDecodeError)):
            return ErrorCategory.LOGIC
        if "schema" in str(error).lower() and "mismatch" in str(error).lower():
            return ErrorCategory.LOGIC
        if output and output.strip().startswith("{"):
            try:
                parsed = json.loads(output)
                if isinstance(parsed, dict) and "columns" in parsed:
                    # Column count check happens externally; here just tag category
                    return ErrorCategory.LOGIC
            except Exception:
                pass
        if "unknown generator" in str(error).lower() or "invalid generator" in str(error).lower():
            return ErrorCategory.LOGIC
        if "param" in str(error).lower() and "type" in str(error).lower():
            return ErrorCategory.LOGIC

        # === QUALITY (insufficient quality, degrade) ===
        if output is None or output.strip() in ("", "{}"):
            return ErrorCategory.QUALITY
        if output and len(output.strip()) < 50:
            return ErrorCategory.QUALITY

        # === Default: unknown errors -> QUALITY (degrade, don't crash pipeline) ===
        return ErrorCategory.QUALITY


# ── Spec §6.6: StagedSchemaAnalyzer (flag-switched entry point) ───────
# Full implementation in Task 7+


class StagedSchemaAnalyzer:
    """Staged LLM analysis entry point.

    Replaces SchemaSemanticAnalyzer.analyze() via flag switch, but does
    NOT delete existing class. Switched via AIConfig.use_staged_pipeline:
      - False (default): existing SchemaSemanticAnalyzer (backward compat)
      - True: this staged pipeline (new)

    Reuse relationships:
      - Stage 1/2 LLM calls: reuse SchemaAnalyzer._call_llm_once() (low-level client)
      - Stage 2 per_column retry: reuse AiConfigRefiner retry logic
      - Stage 3 auto-fix: call existing SchemaSemanticAnalyzer._auto_fix_config
        (rules 1-13, refactored to public function in Task 8) +
        new Stage3Validator (rules 14-16)
    """

    def __init__(self, config: AIConfig | None = None) -> None:
        self._config = config
        self._semantic_analyzer: SchemaSemanticAnalyzer | None = None
        self._low_level_analyzer: Any = None  # SchemaAnalyzer, lazy-init

    # Full implementation in Task 7 (stage 1) + Task 8 (stage 2) + Task 10 (stage 3)
    def analyze(
        self,
        db: Any,
        *,
        tables: list[str] | None = None,
        include_dependencies: bool = True,
        max_depth: int = 5,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """Analyze database via staged pipeline.

        Implemented incrementally:
          - Stage 1 (this task): structure analysis with fallback
          - Stage 2 (Task 8): per_column column analysis
          - Stage 3 (Task 10): validation + auto-fix
        """
        from sqlseed_ai.stage_relevance import determine_stage_relevance

        from sqlseed.core.features import StructuralFeatureExtractor

        # Pre-check: extract structural features
        extractor = StructuralFeatureExtractor(db)
        features = extractor.extract(table_names=tables)
        # Stage relevance computed for stage 2/3 wiring (Task 8/10); stage 1
        # does not consume it directly, but the call validates the pipeline.
        determine_stage_relevance(features)

        # Stage 1: structure analysis (with fallback on LLM failure)
        summary = self._run_stage1_with_fallback(features)

        # Stage 2 + 3 are wired up in Task 11 (full integration).
        # In this Task 7 we return a minimal config dict derived purely from
        # the deterministic stage-1 fallback, so the public analyze() entry
        # point is callable end-to-end without waiting for Task 11.
        tables_config: list[dict[str, Any]] = []
        for table_name in summary.topological_order:
            table_features = next(
                (t for t in features.tables if t.name == table_name),
                None,
            )
            if table_features is None:
                continue
            # Skip autoincrement PK columns (LLM stage 2 will handle in Task 8)
            skippable = self._get_skippable_columns(table_features)
            columns = [
                {"name": c.name, "generator": "string", "params": {}}
                for c in table_features.columns
                if c.name not in skippable
            ]
            tables_config.append({"name": table_name, "columns": columns})
        return {"tables": tables_config}

    def _run_stage1_with_fallback(self, features: StructuralFeatures) -> StructureSummary:
        """Run stage 1 with deterministic fallback on LLM failure (P3 #4)."""
        # Try LLM call first (max 3 retries)
        for attempt in range(3):
            try:
                return self._call_stage1_llm(features)
            except Exception as e:
                logger.warning(
                    "Stage 1 LLM call failed, attempting fallback",
                    attempt=attempt + 1,
                    error=str(e)[:200],
                )
                category = ErrorClassifier.classify(e)
                if category == ErrorCategory.TRANSIENT and attempt < 2:
                    continue
                # LOGIC/QUALITY or TRANSIENT exhausted: use deterministic fallback
                break

        # P3 #4 fix: deterministic fallback StructureSummary
        logger.warning("Stage 1 falling back to deterministic summary (LLM unavailable)")
        return self._build_deterministic_fallback(features)

    def _call_stage1_llm(self, features: StructuralFeatures) -> StructureSummary:
        """Call LLM for stage 1 (will be fully implemented; raises if LLM unavailable)."""
        # Build prompt
        from sqlseed_ai._stage_prompts import (
            STAGE1_SYSTEM_PROMPT,
            STAGE1_USER_TEMPLATE,
        )

        tables_summary = "\n".join(
            f"- {t.name}: {len(t.columns)} cols, "
            f"{len(t.foreign_keys)} FKs, {len(t.check_constraints)} CHECKs, "
            f"{len(t.unique_constraints)} UNIQUEs"
            for t in features.tables
        )
        fk_summary = "\n".join(
            f"- {t.name}.{fk.columns} -> {fk.ref_table}.{fk.ref_columns}"
            for t in features.tables
            for fk in t.foreign_keys
        )
        user_prompt = STAGE1_USER_TEMPLATE.format(
            dialect=features.dialect,
            tables_summary=tables_summary,
            fk_summary=fk_summary or "(none)",
        )

        # Call LLM (reuse existing SchemaAnalyzer if available)
        if self._low_level_analyzer is None:
            raise RuntimeError("Low-level analyzer not configured")

        messages = [
            {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        response = self._low_level_analyzer._call_llm_once(messages)
        return self._parse_stage1_response(response, features)

    def _parse_stage1_response(self, response: str, features: StructuralFeatures) -> StructureSummary:
        """Parse LLM JSON response into StructureSummary."""
        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from LLM: {e}") from e

        # Build StructureSummary from parsed JSON
        tables = []
        for t in data.get("tables", []):
            cross_checks = self._extract_cross_column_checks(t["name"], features)
            tables.append(
                TableStructureSummary(
                    name=t["name"],
                    purpose=t.get("purpose", ""),
                    anchor_columns=t.get("anchor_columns", []),
                    naming_prefix=t.get("naming_prefix", self._derive_naming_prefix(t["name"])),
                    complexity=t.get("complexity", 0),
                    cross_column_checks=cross_checks,
                    fk_references=[],
                )
            )
        return StructureSummary(
            schema_hash=features.schema_hash,
            topological_order=data.get("topological_order", [t.name for t in features.tables]),
            fk_graph=data.get("fk_graph", []),
            tables=tables,
            naming_conventions=data.get("naming_conventions", {t.name: t.naming_prefix for t in tables}),
            complexity_score=data.get(
                "complexity_score",
                {
                    "tables": len(features.tables),
                    "avg_columns": sum(len(t.columns) for t in features.tables) // max(len(features.tables), 1),
                    "avg_constraints": 0,
                },
            ),
            dialect=features.dialect,
        )

    def _build_deterministic_fallback(self, features: StructuralFeatures) -> StructureSummary:
        """P3 #4 fix: deterministic StructureSummary derived purely from features.

        No LLM, no business logic heuristics. Just mechanical derivations:
        - naming_prefix: first 4 chars of table name uppercased + "-"
        - purpose: empty (LLM-inferred, not available in fallback)
        - anchor_columns: PK + UNIQUE columns
        - topological_order: from _topological_sort()
        - complexity: column_count * constraint_count
        """
        tables_summary = []
        for t in features.tables:
            unique_cols = [col for uc in t.unique_constraints for col in uc.columns]
            anchor = list(dict.fromkeys(t.primary_key + unique_cols))[:3]
            complexity = len(t.columns) * (len(t.foreign_keys) + len(t.unique_constraints) + len(t.check_constraints))
            tables_summary.append(
                TableStructureSummary(
                    name=t.name,
                    purpose="",  # Cannot infer without LLM
                    anchor_columns=anchor,
                    naming_prefix=self._derive_naming_prefix(t.name),
                    complexity=complexity,
                    cross_column_checks=self._extract_cross_column_checks(t.name, features),
                    fk_references=[],
                )
            )
        return StructureSummary(
            schema_hash=features.schema_hash,
            topological_order=self._topological_sort(features),
            fk_graph=[
                {"parent": fk.ref_table, "child": t.name, "col": fk.columns[0]}
                for t in features.tables
                for fk in t.foreign_keys
            ],
            tables=tables_summary,
            naming_conventions={t.name: t.naming_prefix for t in tables_summary},
            complexity_score={
                "tables": len(features.tables),
                "avg_columns": sum(len(t.columns) for t in features.tables) // max(len(features.tables), 1),
                "avg_constraints": sum(
                    len(t.foreign_keys) + len(t.unique_constraints) + len(t.check_constraints) for t in features.tables
                )
                // max(len(features.tables), 1),
            },
            dialect=features.dialect,
        )

    def _derive_naming_prefix(self, table_name: str) -> str:
        """Derive naming prefix from table name (first 4 chars upper + '-')."""
        # Take first 4 alphanumeric chars, uppercase, add dash
        prefix_chars = "".join(c for c in table_name[:5] if c.isalnum())[:4]
        return prefix_chars.upper() + "-"

    def _topological_sort(self, features: StructuralFeatures) -> list[str]:
        """Topological sort: FK parents before children (Kahn's algorithm)."""
        # Build adjacency: parent -> [children]
        children: dict[str, list[str]] = {t.name: [] for t in features.tables}
        in_degree: dict[str, int] = {t.name: 0 for t in features.tables}
        for t in features.tables:
            for fk in t.foreign_keys:
                if fk.ref_table in in_degree:
                    children[fk.ref_table].append(t.name)
                    in_degree[t.name] += 1
        # Kahn's algorithm
        queue = sorted([n for n, d in in_degree.items() if d == 0])
        result = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for child in sorted(children[node]):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        return result

    def _extract_cross_column_checks(self, table_name: str, features: StructuralFeatures) -> list[dict[str, Any]]:
        """Extract cross-column CHECK constraints for a table (for per_column context)."""
        table = next((t for t in features.tables if t.name == table_name), None)
        if table is None:
            return []
        result = []
        for chk in table.check_constraints:
            if len(chk.columns) > 1:
                # Build column name -> type map
                col_types = {c.name: c.type for c in table.columns}
                result.append(
                    {
                        "expression": chk.expression,
                        "columns": {col: col_types.get(col, "UNKNOWN") for col in chk.columns},
                    }
                )
        return result

    def _get_skippable_columns(self, table_features: Any) -> list[str]:
        """Return columns to skip in stage 2 (PK/AUTOINCREMENT/GENERATED/DEFAULT)."""
        return [c.name for c in table_features.columns if (c.is_primary_key and c.is_autoincrement) or c.is_computed]
