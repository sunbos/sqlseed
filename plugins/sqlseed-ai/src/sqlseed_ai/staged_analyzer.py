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

    from sqlseed.core.features import ColumnFeatures, StructuralFeatures, TableFeatures

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


# ── Spec §6.2: dynamic granularity decision ──────────────────────────


def decide_granularity(
    features: StructuralFeatures, *, model_id: str
) -> str:
    """Choose stage 2 granularity: 'per_column' | 'per_table' | 'per_db'.

    Spec §6.2 complexity_score (P2 #3 simple version):
      score = (#tables) + (#fk_columns) + 2 * (#check_constraints) + (#unique_columns)

    Decision matrix (P2 #3 simple version):
      - E2B (2B):  score >= 1           -> per_column
      - E4B (4B):  score >= 5           -> per_column; else per_table
      - 12B+:      score >= 10          -> per_column; else per_table
      - 26B+/31B+: score >= 20          -> per_table; else per_db
      - Unknown model id: default per_column (safest)

    Args:
        features: Layer 1 structural features.
        model_id: LLM model id (e.g., "gemma-4-e2b-it").

    Returns:
        One of 'per_column', 'per_table', 'per_db'.
    """
    score = _compute_complexity_score(features)
    model_lower = (model_id or "").lower()

    if "e2b" in model_lower:
        # 2B: always per_column (smallest context per call)
        return "per_column"
    if "e4b" in model_lower:
        return "per_column" if score >= 5 else "per_table"
    if "12b" in model_lower:
        return "per_column" if score >= 10 else "per_table"
    # 26B / 31B / unknown-large: prefer per_db for simplicity
    if "26b" in model_lower or "31b" in model_lower:
        return "per_table" if score >= 20 else "per_db"
    # Unknown model: safest = per_column (most LLM calls, smallest context each)
    return "per_column"


def _compute_complexity_score(features: StructuralFeatures) -> int:
    """Spec §6.2 simple complexity_score (P2 #3 simple version)."""
    score = 0
    for t in features.tables:
        score += 1  # one per table
        score += sum(len(fk.columns) for fk in t.foreign_keys)
        score += 2 * len(t.check_constraints)
        score += sum(len(u.columns) for u in t.unique_constraints)
    return score


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
        self._validator = Stage3Validator()

    def _get_low_level_analyzer(self) -> Any:
        """Lazy-init the low-level SchemaAnalyzer used for raw LLM calls.

        Mirrors ``SchemaSemanticAnalyzer._analyzer`` property: when the staged
        pipeline is invoked with a real ``AIConfig`` (e.g. via the CLI), the
        SchemaAnalyzer is constructed on first use so module import does not
        require a configured backend.
        """
        if self._low_level_analyzer is None:
            from sqlseed_ai.analyzer import SchemaAnalyzer

            self._low_level_analyzer = SchemaAnalyzer(config=self._config)
        return self._low_level_analyzer

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

        Full pipeline (Task 11 integration):
          - Layer 1: extract StructuralFeatures via StructuralFeatureExtractor
          - Stage 1: _run_stage1_with_fallback -> StructureSummary
          - Stage 2: _run_stage2_per_column(features, summary, target_tables)
                     returns config dict with all tables/columns
          - Stage 3: _run_stage3_validate (auto-fix rules #1-#16)
        """
        from sqlseed_ai.stage_relevance import determine_stage_relevance

        from sqlseed.core.features import StructuralFeatureExtractor

        # Layer 1: extract structural features
        extractor = StructuralFeatureExtractor(db)
        features = extractor.extract(table_names=tables)
        determine_stage_relevance(features)  # Side-effect-free; future use

        # Stage 1: structure analysis (with deterministic fallback on LLM failure)
        summary: StructureSummary = self._run_stage1_with_fallback(features)

        # Stage 2: per_column analysis (returns full config dict).
        # _run_stage2_per_column is defined in Task 8 with this exact signature:
        #   (features, summary, target_tables) -> dict[str, Any]
        target_tables = tables if tables is not None else summary.topological_order
        config: dict[str, Any] = self._run_stage2_per_column(
            features,
            summary,
            target_tables,
        )

        # Stage 3: validate + auto-fix rules #1-#13 (Task 9) + #14-#16 (Task 10)
        return self._run_stage3_validate(config, features)

    def _run_stage3_validate(
        self,
        config: dict[str, Any],
        features: StructuralFeatures,
    ) -> dict[str, Any]:
        """Stage 3: apply existing rules #1-#13 + new rules #14-#16 in place."""
        # Existing rules #1-#13 (extracted in Task 9 as public function)
        from sqlseed_ai.schema_analyzer import apply_auto_fix_rules_1_13

        schema_dict = self._features_to_schema_dict(features)
        config = apply_auto_fix_rules_1_13(config, schema_dict)

        # New rules #14-#16 (Task 10 Stage3Validator)
        return self._validator.validate(config, schema=schema_dict)

    def _features_to_schema_dict(
        self,
        features: StructuralFeatures,
    ) -> dict[str, dict[str, Any]]:
        """Convert StructuralFeatures to legacy schema dict shape.

        apply_auto_fix_rules_1_13() expects dict[str, dict] with keys
        'columns' / 'primary_keys' / 'foreign_keys' / 'unique_indexes' /
        'unique_columns' / 'check_constraints' — same shape that
        SchemaSemanticAnalyzer._auto_fix_config used to receive.
        """
        result: dict[str, dict[str, Any]] = {}
        for t in features.tables:
            # Build set of FK column names for is_foreign_key flag (Fix 13 needs it)
            fk_col_names: set[str] = set()
            for fk in t.foreign_keys:
                for col in fk.columns:
                    fk_col_names.add(col)
            result[t.name] = {
                "columns": [
                    {
                        "name": c.name,
                        "type": c.type,
                        "nullable": c.nullable,
                        "default": c.default,
                        "is_primary_key": c.is_primary_key,
                        "is_autoincrement": c.is_autoincrement,
                        "is_computed": c.is_computed,
                        "is_foreign_key": c.name in fk_col_names,
                    }
                    for c in t.columns
                ],
                "primary_keys": list(t.primary_key),  # CORRECTED: primary_key (singular)
                "foreign_keys": [
                    {
                        "columns": list(fk.columns),
                        "ref_table": fk.ref_table,
                        "ref_columns": list(fk.ref_columns),
                    }
                    for fk in t.foreign_keys
                ],
                # UniqueConstraintFeatures has no `name` field; the auto-fix
                # rules only read `unique` and `columns` from unique_indexes,
                # so we omit `name` entirely (cleaner than a synthetic name).
                "unique_indexes": [{"columns": list(u.columns), "unique": True} for u in t.unique_constraints],
                "unique_columns": [col for u in t.unique_constraints for col in u.columns],
                "check_constraints": [
                    {"name": c.name, "columns": list(c.columns), "expression": c.expression}
                    for c in t.check_constraints
                ],
            }
        return result

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

        # Call LLM (lazy-init SchemaAnalyzer on first use)
        messages = [
            {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        response = self._get_low_level_analyzer()._call_llm_once(messages)
        return self._parse_stage1_response(response, features)

    def _parse_stage1_response(self, response: str | dict[str, Any], features: StructuralFeatures) -> StructureSummary:
        """Parse LLM JSON response into StructureSummary.

        ``SchemaAnalyzer._call_llm_once`` returns a parsed dict directly; we
        also accept a raw JSON string for testability and backward compat.
        """
        if isinstance(response, dict):
            data = response
        else:
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

    def _run_stage2_per_column(
        self,
        features: StructuralFeatures,
        summary: StructureSummary,
        target_tables: list[str],
    ) -> dict[str, Any]:
        """Stage 2: per_column analysis (2B model recommended).

        Spec §6.1 per_column mode:
          - Input per call: 1 column constraints + structure summary
            + same-table cross-column CHECK context (P1 #3 fix)
          - Output: {column, generator, params, derive_from, expression}
          - Skip: PK/AUTOINCREMENT/GENERATED/DEFAULT (auto-fix handles)
        """
        from sqlseed_ai._stage_prompts import (
            STAGE2_PER_COLUMN_SYSTEM_PROMPT,
            STAGE2_PER_COLUMN_USER_TEMPLATE,
        )

        all_tables_config: list[dict[str, Any]] = []
        for table_name in summary.topological_order:
            if target_tables and table_name not in target_tables:
                continue
            table_features = next((t for t in features.tables if t.name == table_name), None)
            if table_features is None:
                continue
            table_summary = next((t for t in summary.tables if t.name == table_name), None)
            naming_prefix = table_summary.naming_prefix if table_summary else self._derive_naming_prefix(table_name)
            cross_checks = self._extract_cross_column_checks(table_name, features)
            skip_cols = self._get_skippable_columns(table_features)

            columns_config: list[dict[str, Any]] = []
            for col in table_features.columns:
                if col.name in skip_cols:
                    continue
                # Build per-column prompt with cross-column context
                fk_summary = self._format_fks_for_prompt(table_features)
                cross_checks_str = self._format_cross_checks_for_prompt(cross_checks)
                user_prompt = STAGE2_PER_COLUMN_USER_TEMPLATE.format(
                    table_name=table_name,
                    naming_prefix=naming_prefix,
                    column_name=col.name,
                    column_type=col.type,
                    nullable=col.nullable,
                    default=col.default,
                    is_pk=col.is_primary_key,
                    is_autoincrement=col.is_autoincrement,
                    is_computed=col.is_computed,
                    is_unique=self._is_column_unique(table_features, col.name),
                    cross_column_checks=cross_checks_str,
                    foreign_keys=fk_summary,
                )
                messages = [
                    {"role": "system", "content": STAGE2_PER_COLUMN_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ]
                try:
                    response = self._get_low_level_analyzer()._call_llm_once(messages)
                    col_config = self._parse_stage2_response(response)
                    col_config.pop("column", None)  # remove LLM-returned "column" key to avoid clash with "name"
                    col_config["name"] = col.name
                    columns_config.append(col_config)
                except Exception as e:
                    category = ErrorClassifier.classify(e)
                    if category == ErrorCategory.TRANSIENT:
                        # Retry once
                        try:
                            response = self._get_low_level_analyzer()._call_llm_once(messages)
                            col_config = self._parse_stage2_response(response)
                            col_config.pop("column", None)
                            col_config["name"] = col.name
                            columns_config.append(col_config)
                            continue
                        except Exception:
                            pass
                    # LOGIC/QUALITY or retry failed: degrade to type-routed config
                    logger.warning(
                        "Stage 2 column analysis failed, degrading to type-routed config",
                        table=table_name,
                        column=col.name,
                        error=str(e)[:200],
                    )
                    columns_config.append(self._degrade_to_type_routed(col))

            all_tables_config.append(
                {
                    "name": table_name,
                    "columns": columns_config,
                }
            )

        return {"tables": all_tables_config}

    def _is_column_unique(self, table: TableFeatures, column_name: str) -> bool:
        """Check if column is UNIQUE."""
        return any(column_name in uc.columns for uc in table.unique_constraints)

    def _format_fks_for_prompt(self, table: TableFeatures) -> str:
        """Format FKs for prompt injection."""
        if not table.foreign_keys:
            return "(none)"
        return "\n".join(f"- {fk.columns} -> {fk.ref_table}.{fk.ref_columns}" for fk in table.foreign_keys)

    def _format_cross_checks_for_prompt(self, cross_checks: list[dict[str, Any]]) -> str:
        """P1 #3 fix: format cross-column CHECKs for prompt injection."""
        if not cross_checks:
            return "(none)"
        return "\n".join(f"- {chk['expression']} (columns: {chk['columns']})" for chk in cross_checks)

    def _parse_stage2_response(self, response: str | dict[str, Any]) -> dict[str, Any]:
        """Parse LLM stage 2 response.

        ``SchemaAnalyzer._call_llm_once`` returns a parsed dict directly; we
        also accept a raw JSON string for testability and backward compat.
        """
        if isinstance(response, dict):
            return response
        try:
            data = json.loads(response)
            if not isinstance(data, dict):
                raise ValueError("Response is not a JSON object")
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from LLM: {e}") from e

    def _degrade_to_type_routed(self, col: ColumnFeatures) -> dict[str, Any]:
        """Degrade to type-routed minimal config (QUALITY fallback)."""
        type_upper = col.type.upper()
        if "INT" in type_upper:
            generator = "integer"
            params: dict[str, Any] = {"min_value": 0, "max_value": 99999}
        elif any(t in type_upper for t in ("REAL", "FLOAT", "DOUBLE", "DECIMAL")):
            generator = "float"
            params = {"min_value": 0.0, "max_value": 9999.0}
        elif "BOOL" in type_upper:
            generator = "boolean"
            params = {}
        elif "DATE" in type_upper and "TIME" not in type_upper:
            generator = "date"
            params = {}
        elif any(t in type_upper for t in ("DATETIME", "TIMESTAMP")):
            generator = "datetime"
            params = {}
        else:
            generator = "string"
            params = {"min_length": 1, "max_length": 100}
        return {
            "name": col.name,
            "generator": generator,
            "params": params,
            "derive_from": None,
            "expression": None,
        }

    def _get_skippable_columns(self, table: TableFeatures) -> set[str]:
        """Skip PK + AUTOINCREMENT + GENERATED + DEFAULT (handled by auto-fix)."""
        skip = set()
        for col in table.columns:
            if (col.is_primary_key and col.is_autoincrement) or col.is_computed:
                skip.add(col.name)
        return skip


# ── Spec §6.1 stage 3: Stage3Validator (rules #14-#16) ───────────────


# Rule #14: GENERATOR_PARAMS whitelist — based on src/sqlseed/generators/base_provider.py
# Each generator's accepted keyword arguments. Params not in this list are stripped.
_GENERATOR_ACCEPTED_PARAMS: dict[str, set[str]] = {
    "string": {"min_length", "max_length", "charset"},
    "integer": {"min_value", "max_value"},
    "float": {"min_value", "max_value", "precision"},
    "boolean": set(),
    "bytes": {"length"},
    "name": set(),
    "first_name": set(),
    "last_name": set(),
    "email": set(),
    "phone": set(),
    "address": set(),
    "company": set(),
    "url": set(),
    "ipv4": set(),
    "uuid": set(),
    "date": {"start_year", "end_year"},
    "datetime": {"start_year", "end_year"},
    "timestamp": set(),
    "text": {"min_length", "max_length"},
    "sentence": set(),
    "password": {"length"},
    "choice": {"choices"},
    "json": {"schema"},
    "pattern": {"pattern", "regex"},
    "username": set(),
    "city": set(),
    "country": set(),
    "state": set(),
    "zip_code": set(),
    "job_title": set(),
    "country_code": set(),
    "word": set(),  # word takes NO params (P2 #1 root cause)
    "template": {"template", "sequence_start", "sequence_step"},
    "weighted_choice": {"choices", "weighted_choices"},
}

# Rule #15: regex patterns that match unbounded quantifiers {N,}
_UNBOUNDED_REGEX_PATTERN = re.compile(r"\{(\d+),\}")


class Stage3Validator:
    """Stage 3 validator: apply auto-fix rules #14-#16 on top of LLM output.

    Rule #14: GENERATOR_PARAMS validation — strip params not accepted by generator.
    Rule #15: bounds unbounded regex quantifiers {N,} -> {N,N+5}.
    Rule #16: FK semantic check — FK columns must use a generator compatible with
              the referenced column's type.
    """

    def validate(
        self,
        config: dict[str, Any],
        *,
        schema: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Apply all Stage 3 rules in-place. Returns the same config dict."""
        for table in config.get("tables", []):
            table_name = table.get("name")
            if not isinstance(table_name, str):
                continue
            for col in table.get("columns", []):
                if not isinstance(col, dict):
                    continue
                self._apply_rule_14_strip_invalid_params(col)
                self._apply_rule_15_bound_regex(col)
            if schema and table_name in schema:
                self._apply_rule_16_fk_semantic(table, schema[table_name])
        return config

    def _apply_rule_14_strip_invalid_params(self, col: dict[str, Any]) -> None:
        """Rule #14: strip params not in generator's accepted whitelist."""
        gen = col.get("generator")
        if not isinstance(gen, str):
            return
        accepted = _GENERATOR_ACCEPTED_PARAMS.get(gen)
        if accepted is None:
            # Unknown generator — leave params alone (let core raise at runtime)
            return
        params = col.get("params")
        if not isinstance(params, dict):
            return
        invalid_keys = set(params.keys()) - accepted
        for key in invalid_keys:
            logger.warning(
                "Stage3 Rule #14: stripping invalid param for generator",
                generator=gen,
                param=key,
            )
            params.pop(key, None)

    def _apply_rule_15_bound_regex(self, col: dict[str, Any]) -> None:
        """Rule #15: bound unbounded regex quantifiers {N,} -> {N,N+5}."""
        if col.get("generator") not in ("pattern",):
            return
        params = col.get("params")
        if not isinstance(params, dict):
            return
        for key in ("regex", "pattern"):
            val = params.get(key)
            if not isinstance(val, str):
                continue
            # Replace each {N,} with {N,N+5}
            new_val = _UNBOUNDED_REGEX_PATTERN.sub(_bound_unbounded_quantifier, val)
            if new_val != val:
                logger.warning(
                    "Stage3 Rule #15: bounding unbounded regex quantifier",
                    original=val,
                    bounded=new_val,
                )
                params[key] = new_val

    def _apply_rule_16_fk_semantic(self, table: dict[str, Any], table_schema: dict[str, Any]) -> None:
        """Rule #16: FK columns must use a generator compatible with ref column type.

        Currently only checks: FK to integer column must use integer generator
        (common LLM mistake: assigning username/name to FK columns ending in _by).
        """
        fks = table_schema.get("foreign_keys", [])
        if not isinstance(fks, list):
            return
        # Build set of FK column names whose ref column is integer-like.
        # Note: ref column type is not always available in schema snapshot;
        # we assume "id" / "user_id" / "*_id" ref columns are integers.
        integer_fk_cols: set[str] = set()
        for fk in fks:
            if not isinstance(fk, dict):
                continue
            ref_cols = fk.get("ref_columns", [])
            if not ref_cols:
                continue
            ref_col_lower = str(ref_cols[0]).lower()
            # Heuristic: ref column ending in "id" is integer (PK autoincrement).
            if ref_col_lower.endswith("id"):
                for col_in_fk in fk.get("columns", []):
                    integer_fk_cols.add(col_in_fk)

        for col in table.get("columns", []):
            if not isinstance(col, dict):
                continue
            col_name = col.get("name")
            if col_name not in integer_fk_cols:
                continue
            gen = col.get("generator")
            # Integer-compatible generators
            if gen in ("integer", "uuid", "pattern"):
                continue
            logger.warning(
                "Stage3 Rule #16: replacing string generator on integer FK column",
                column=col_name,
                original_generator=gen,
                ref_column_type="integer",
            )
            col["generator"] = "integer"
            col["params"] = {"min_value": 1, "max_value": 999999}


def _bound_unbounded_quantifier(match: re.Match[str]) -> str:
    """Replace {N,} with {N,N+5} (module-level helper to satisfy B023)."""
    n = int(match.group(1))
    return f"{{{n},{n + 5}}}"
