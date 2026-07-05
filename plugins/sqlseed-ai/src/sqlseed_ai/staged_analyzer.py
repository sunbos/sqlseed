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
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.config import AIConfig
    from sqlseed_ai.repair.pipeline import RepairPipeline
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


def decide_granularity(features: StructuralFeatures, *, model_id: str) -> str:
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

    def __init__(
        self,
        config: AIConfig | None = None,
        *,
        db_path: str | None = None,
        url: str | None = None,
    ) -> None:
        self._config = config
        self._semantic_analyzer: SchemaSemanticAnalyzer | None = None
        self._low_level_analyzer: Any = None  # SchemaAnalyzer, lazy-init
        # Pass db_path/url to Stage3Validator so the dual-track pipeline
        # (RepairPipeline alongside legacy rules) is activated when a DB
        # connection is available. Without this, _dual_track_enabled is
        # always False and the new repair path is dead code.
        self._validator = Stage3Validator(db_path=db_path, url=url)

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

        # P3 #5 fix: enrich UNIQUE constraints that SQLAlchemy's get_indexes()
        # misses (column-level UNIQUE like ``email TEXT UNIQUE`` creates
        # sqlite_autoindex_* which get_indexes() filters out). This is a
        # plugin-layer workaround for a core extraction gap — the legacy
        # SchemaSemanticAnalyzer had the same PRAGMA fallback inline.
        self._enrich_unique_constraints_from_db(features, db)

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

    def _enrich_unique_constraints_from_db(
        self,
        features: StructuralFeatures,
        db: Any,
    ) -> None:
        """Enrich UNIQUE constraints that SQLAlchemy's get_indexes() misses.

        SQLAlchemy's ``inspector.get_indexes()`` filters out implicit
        auto-indexes created by column-level UNIQUE constraints (e.g.,
        ``email TEXT UNIQUE`` creates ``sqlite_autoindex_*``). This leaves
        ``features.tables[i].unique_constraints`` empty for tables that use
        inline UNIQUE, which breaks Rule #24 (UNIQUE-aware template upgrade)
        and rules #1-#13 that set ``constraints.unique=true``.

        This plugin-layer workaround queries the DB directly:
          - SQLite: ``PRAGMA index_list`` + ``PRAGMA index_info`` (same
            approach as the legacy ``SchemaSemanticAnalyzer._get_schema``).
          - Other dialects: best-effort via ``hasattr`` probe of the
            adapter's underlying inspector; silently skips on failure.

        Mutates ``features.tables[i].unique_constraints`` in place by
        appending any UNIQUE columns not already present. Idempotent:
        re-running on an already-enriched features object is a no-op.
        """
        from sqlseed._utils.sql_safe import quote_identifier

        # Detect dialect via the adapter's public ``dialect`` property when
        # available; fall back to a conservative string probe.
        dialect_name = ""
        try:
            dialect_obj = getattr(db, "dialect", None)
            if dialect_obj is not None and hasattr(dialect_obj, "name"):
                dialect_name = dialect_obj.name
        except Exception as exc:
            logger.debug("Dialect detection failed", error=str(exc)[:120])

        for table_features in features.tables:
            table_name = table_features.name
            # Collect UNIQUE columns already known (idempotency guard).
            existing_unique_cols: set[str] = set()
            for uc in table_features.unique_constraints:
                for col in uc.columns:
                    existing_unique_cols.add(col)

            new_unique_cols: list[str] = []
            if dialect_name == "sqlite":
                # PRAGMA index_list returns: (seq, name, unique, origin, partial)
                # PRAGMA index_info(name) returns: (seqno, cid, name)
                try:
                    safe_table = quote_identifier(table_name)
                    result = db.execute(f"PRAGMA index_list({safe_table})")
                    rows = result.fetchall() if hasattr(result, "fetchall") else []
                    for row in rows:
                        if len(row) >= 3 and row[2]:
                            idx_name = row[1]
                            idx_result = db.execute(f"PRAGMA index_info({quote_identifier(idx_name)})")
                            idx_rows = idx_result.fetchall() if hasattr(idx_result, "fetchall") else []
                            for ir in idx_rows:
                                if len(ir) >= 3 and ir[2]:
                                    new_unique_cols.append(ir[2])
                except Exception as exc:
                    logger.debug(
                        "PRAGMA index_list fallback failed",
                        table=table_name,
                        error=str(exc)[:120],
                    )
            else:
                # Non-SQLite: try SQLAlchemy inspector.get_unique_constraints().
                # The adapter may expose the inspector via a private attribute;
                # probe defensively since the Protocol doesn't guarantee it.
                inspector = getattr(db, "_inspector", None)
                if inspector is not None and hasattr(inspector, "get_unique_constraints"):
                    try:
                        ucs = inspector.get_unique_constraints(table_name)
                        for uc in ucs:
                            for col in uc.get("column_names", []):
                                if col:
                                    new_unique_cols.append(col)
                    except Exception as exc:
                        logger.debug(
                            "get_unique_constraints failed",
                            table=table_name,
                            error=str(exc)[:120],
                        )

            # Append newly-discovered UNIQUE columns (dedup against existing).
            from sqlseed.core.features import UniqueConstraintFeatures

            added: list[str] = []
            for col in new_unique_cols:
                if col in existing_unique_cols:
                    continue
                existing_unique_cols.add(col)
                added.append(col)
            if added:
                table_features.unique_constraints.append(
                    UniqueConstraintFeatures(
                        table=table_name,
                        columns=added,
                        is_index_based=True,
                    )
                )
                logger.info(
                    "Enriched UNIQUE constraints from DB",
                    table=table_name,
                    columns=added,
                )

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
    "catch_phrase": set(),  # catch_phrase takes NO params
    "template": {"template", "sequence_start", "sequence_step"},
    "weighted_choice": {"choices", "weighted_choices"},
}

# Rule #15: regex patterns that match unbounded quantifiers {N,}
_UNBOUNDED_REGEX_PATTERN = re.compile(r"\{(\d+),\}")

# Rule #28: subset of ColumnMapper.EXACT_MATCH_RULES that have unambiguous
# semantic meaning. When the LLM picks a generic generator (string/text/word)
# for one of these column names, the exact-match generator is semantically
# correct and should override. Only unambiguous names are included — names
# like "state" (could mean US state or order status) or "status" (choice
# generator, but LLM might have a domain-specific reason) are excluded.
_EXACT_MATCH_UPGRADE_RULES: dict[str, tuple[str, dict[str, Any]]] = {
    "email": ("email", {}),
    "phone": ("phone", {}),
    "telephone": ("phone", {}),
    "mobile": ("phone", {}),
    "address": ("address", {}),
    "url": ("url", {}),
    "website": ("url", {}),
    "homepage": ("url", {}),
    "avatar": ("url", {}),
    "avatar_url": ("url", {}),
    "uuid": ("uuid", {}),
    "guid": ("uuid", {}),
    "token": ("uuid", {}),
    "password": ("password", {}),
    "passwd": ("password", {}),
    "secret": ("password", {}),
    "city": ("city", {}),
    "country": ("country", {}),
    "zip_code": ("zip_code", {}),
    "postal_code": ("zip_code", {}),
    "postcode": ("zip_code", {}),
    "country_code": ("country_code", {}),
    "job_title": ("job_title", {}),
    "occupation": ("job_title", {}),
    "position": ("job_title", {}),
    "location": ("city", {}),
    # Text-content columns: sentence is semantically closer to a real
    # description/comment than a single random word or generic text blob.
    "title": ("sentence", {}),
    "subject": ("sentence", {}),
    "headline": ("sentence", {}),
    "description": ("sentence", {}),
    "comment": ("sentence", {}),
    "note": ("sentence", {}),
    "remark": ("sentence", {}),
    "username": ("username", {}),
    "user_name": ("username", {}),
    "nickname": ("username", {}),
}

# Rule #28 pattern upgrades: mirror ColumnMapper.PATTERN_MATCH_RULES for
# high-confidence cases where a generic generator (string/text/word) is
# semantically wrong. Ordered most-specific first (person-name prefixes
# before general *_name, etc.) so the strongest match wins.
# Only patterns whose upgrade target is NOT itself generic are included
# (e.g., *_description → text is excluded because text is generic).
_PATTERN_UPGRADE_RULES: tuple[tuple[re.Pattern[str], str, dict[str, Any]], ...] = (
    # Person-name contexts: human-related prefixes → real person names.
    (
        re.compile(
            r".*(?:user|customer|employee|member|author|student|teacher|patient|person|contact|owner|admin|guest|subscriber)_name$"
        ),
        "name",
        {},
    ),
    # High-confidence domain contexts: organization prefixes → company.
    (
        re.compile(r".*(?:company|org|organization|department|unit|vendor|supplier|brand)_name$"),
        "company",
        {},
    ),
    # General *_name fallback: catch_phrase (multi-word business phrase).
    (re.compile(r".*_name$"), "catch_phrase", {}),
    # Title-like columns: sentence is semantically closer than a single word.
    (re.compile(r".*_title$|.*_subject$|.*_headline$"), "sentence", {}),
    # Contact-info patterns.
    (re.compile(r".*_email$"), "email", {}),
    (re.compile(r".*_phone$|.*_tel$|.*_mobile$"), "phone", {}),
    (re.compile(r".*_url$|.*_link$|.*_href$"), "url", {}),
    # Secrets/credentials.
    (re.compile(r".*_password$|.*_passwd$|.*_secret$"), "password", {}),
    # Address.
    (re.compile(r".*_address$"), "address", {}),
)

# Generators considered "generic" — LLMs pick these when they fail to
# recognize the column's semantic meaning. Rule #28 upgrades these to
# the specific exact-match generator when one exists.
_GENERIC_GENERATORS: frozenset[str] = frozenset({"string", "text", "word"})

# Generators that produce numeric/boolean values — incompatible with
# DATE/TIMESTAMP columns (Rule #30 detects this mismatch).
_NUMERIC_BOOLEAN_GENERATORS: frozenset[str] = frozenset({"integer", "float", "boolean", "random_int", "random_float"})

# Generators that produce date/datetime values — incompatible with
# INTEGER/REAL columns (Rule #30 detects this mismatch).
_DATE_GENERATORS: frozenset[str] = frozenset({"date", "datetime", "timestamp"})

# Generators that accept a 'choices' param (list of values to pick from).
# Rule #14 uses this to normalize list-params into {choices: [...]} format.
_CHOICE_FAMILY_GENERATORS: frozenset[str] = frozenset({"choice", "weighted_choice"})

# All generators that produce non-date values and would crash on DATE/TIMESTAMP
# columns. Used by Rule #30 to detect severe type mismatches.
_ALL_NON_DATE_GENERATORS: frozenset[str] = _NUMERIC_BOOLEAN_GENERATORS | _GENERIC_GENERATORS


class Stage3Validator:
    """Stage 3 validator: apply auto-fix rules #14-#19 on top of LLM output.

    Rule #14: GENERATOR_PARAMS validation — strip params not accepted by generator.
              Also corrects the common LLM typo ``choice`` -> ``choices``.
    Rule #15: bounds unbounded regex quantifiers {N,} -> {N,N+5}.
    Rule #16: FK semantic check — FK columns must use a generator compatible with
              the referenced column's type. Skips columns with derive_from set.
    Rule #17: boolean-expression derive_from detection — rewrites LLM-returned
              boolean comparisons (``>= value``, ``X >= 0 AND X <= value``) into
              valid assignment expressions, or strips derive_from if unrecognised.
    Rule #18: caps unreasonable future ``end_year`` on date/datetime generators
              to ``current_year + 1`` (prevents 22nd-century test data).
    Rule #19: extracts min_value/max_value from simple CHECK constraints
              (``col >= N``, ``col <= N``) and lifts the generator's bounds
              to satisfy the constraint. Skips derive_from columns.
    Rule #27: fills columns with missing generators. If the column participates
              in a cross-column CHECK (e.g., ``sale_price >= cost_price``),
              infers ``derive_from`` + ``expression`` from the constraint so
              the derived value automatically satisfies it. Otherwise falls
              back to a type-routed generator based on the column's SQL type.
    Rule #28: upgrades generic generators (``string``/``text``/``word``) to
              the exact-match generator when the column name has an unambiguous
              semantic mapping (e.g., ``description`` → ``sentence`` instead
              of ``text``; ``email`` → ``email`` instead of ``string``).
    Rule #29: detects and breaks derive_from circular dependencies and
              type-incompatible derive_from (e.g., TEXT column deriving from
              a REAL column). For cycles, removes the derive_from from the
              column that has a weaker claim (non-CHECK-constrained). For
              type incompatibility, strips derive_from and falls back to
              Rule #28 semantic matching or type-routed generator.

    Dual-track (Phase 2 scaffolding): when constructed with ``db_path`` or
    ``url``, a :class:`RepairPipeline` is built alongside the legacy rules.
    The new path runs on a deep copy of the legacy-fixed config and any
    discrepancies are logged as warnings. Full dual-track activation
    (with snapshot-driven repairs overriding legacy output) is deferred to
    Phase 6. When no DB connection is provided, dual-track is disabled and
    only the legacy rules run (backward-compatible with ``Stage3Validator()``).
    """

    def __init__(
        self,
        *,
        db_path: str | None = None,
        url: str | None = None,
    ) -> None:
        """Initialize Stage3Validator with optional dual-track pipeline.

        Args:
            db_path: Optional SQLite database path. When provided, the new
                :class:`RepairPipeline` runs alongside legacy rules and
                discrepancies are logged. When omitted, only legacy rules run.
            url: Optional database URL (alternative to ``db_path``).
        """
        self._db_path = db_path
        self._url = url
        self._dual_track_enabled: bool = db_path is not None or url is not None
        self._new_pipeline: RepairPipeline | None = None
        if self._dual_track_enabled:
            try:
                from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
                from sqlseed_ai.contracts.matrix import ContractResolver
                from sqlseed_ai.repair.pipeline import RepairPipeline

                resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
                self._new_pipeline = RepairPipeline(resolver, db_path=db_path, url=url)
            except ImportError as e:
                logger.warning(
                    "Dual-track pipeline unavailable; falling back to legacy-only",
                    error=str(e),
                )
                self._dual_track_enabled = False
                self._new_pipeline = None

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
            table_schema = schema.get(table_name) if schema and isinstance(schema, dict) else None
            # Rule #27 runs FIRST (table-level): fills missing generators so
            # subsequent column-level rules can process them normally. Must
            # run before Rule #22, which assumes all date columns have a
            # generator (or were stripped by Rule #17, which runs later).
            if table_schema:
                self._apply_rule_27_missing_generator_with_check_inference(table, table_schema)
            for col in table.get("columns", []):
                if not isinstance(col, dict):
                    continue
                # Rule #28 runs before Rule #14: upgrading the generator may
                # change which params are valid (e.g., text→sentence drops
                # min_length/max_length). Rule #14 then strips the now-invalid
                # params for the new generator.
                # Rule #28 skips UNIQUE columns so Rule #24 (which runs later)
                # can upgrade them to template for uniqueness guarantee.
                self._apply_rule_28_exact_match_upgrade(col, table_schema)
                # Rule #30 runs after Rule #28 (semantic upgrade) but before
                # Rule #14 (param stripping): if Rule #30 changes the generator,
                # Rule #14 will then strip params invalid for the new generator.
                self._apply_rule_30_generator_type_compatibility(col, table_schema)
                self._apply_rule_14_strip_invalid_params(col)
                self._apply_rule_15_bound_regex(col)
                self._apply_rule_17_boolean_expression(col, table_schema)
                self._apply_rule_20_sandbox_external_functions(col, table_schema)
                # Rule #26 must run AFTER Rule #20: Rule #20 may rewrite
                # sandbox-external patterns into ``random_float(...)`` (e.g.,
                # ``random() * value`` → ``random_float(0, value)``), and
                # Rule #26 then coerces that to ``random_int`` for INTEGER
                # columns. Running Rule #26 before Rule #20 would miss these.
                self._apply_rule_26_int_column_float_to_int(col, table_schema)
                self._apply_rule_18_cap_future_end_year(col)
                self._apply_rule_23_phone_to_pattern(col)
                # Rule #25 must run BEFORE Rule #24: it converts text→string
                # for code-like columns so Rule #24 Case 2 can subsequently
                # upgrade the string to template when UNIQUE is required.
                self._apply_rule_25_text_to_string_for_codes(col)
                self._apply_rule_24_unique_word_to_template(col, table_schema)
            if table_schema:
                self._apply_rule_16_fk_semantic(table, table_schema)
                self._apply_rule_19_check_constraint_bounds(table, table_schema)
                self._apply_rule_22_cross_column_date_range_isolation(table, table_schema)
                # Rule #29 runs LAST (table-level): detects and breaks derive_from
                # cycles and type-incompatible derive_from that would cause runtime
                # crashes. Must run after Rule #27 (which adds derive_from) and
                # Rule #17 (which strips unsafe derive_from on DATE columns).
                self._apply_rule_29_derive_from_integrity(table, table_schema)
        # Dual-track: run the new RepairPipeline on a deep copy and log
        # discrepancies against the legacy-fixed config (Phase 2 scaffolding).
        # Full dual-track activation (snapshot-driven repairs overriding
        # legacy output) is deferred to Phase 6. Without a DB connection,
        # dual-track is disabled and this branch is skipped.
        self._run_dual_track(config)
        return config

    def _run_dual_track(self, config: dict[str, Any]) -> None:
        """Run the new repair pipeline on a copy and log discrepancies.

        Phase 2 scaffolding: builds a :class:`SchemaSnapshot` from the DB
        connection (when available), runs :class:`RepairPipeline.run()` on a
        deep copy of the legacy-fixed config, and logs any field-level
        discrepancies as warnings. The legacy-fixed config is never mutated
        by the new path in Phase 2; full override behavior arrives in Phase 6.

        Failures in the new path are logged and swallowed so the legacy
        result is always returned to the caller.
        """
        if not self._dual_track_enabled or self._new_pipeline is None:
            return
        import copy

        try:
            from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

            snapshot = SchemaSnapshot(db_path=self._db_path, url=self._url)
            if not snapshot.tables:
                logger.debug(
                    "Dual-track skipped: snapshot has no tables",
                )
                return
            new_config_copy = copy.deepcopy(config)
            _, repair_result = self._new_pipeline.run(new_config_copy, snapshot)
            if repair_result.applied_fixes:
                logger.info(
                    "Dual-track new path applied fixes",
                    fix_count=repair_result.fix_count,
                    unfixable_count=len(repair_result.unfixable),
                )
            if repair_result.unfixable:
                logger.warning(
                    "Dual-track new path found unfixable violations",
                    unfixable_count=len(repair_result.unfixable),
                )
        except Exception as e:  # dual-track must never break legacy path
            logger.warning(
                "Dual-track new path failed; relying on legacy",
                error=str(e),
                error_type=type(e).__name__,
            )

    def _apply_rule_14_strip_invalid_params(self, col: dict[str, Any]) -> None:
        """Rule #14: normalize and strip params not in generator's accepted whitelist.

        This rule performs three layers of params normalization:

        1. **List-to-dict wrapping**: When LLM outputs ``params`` as a bare
           list (e.g., ``['active', 'suspended', 'closed']``) for choice-family
           generators, wrap it as ``{'choices': [...]}``. This is a common LLM
           hallucination — the LLM treats ``params`` as a list of values rather
           than a dict of named parameters.

        2. **weighted_choice downgrade**: When LLM outputs ``weighted_choice``
           but ``choices`` is a list of strings (not ``[{value, weight}, ...]``
           dicts), downgrade to plain ``choice``. The ``weighted_choice`` params
           format is complex and LLMs frequently get it wrong; ``choice``
           produces equivalent output for equal-weight scenarios.

        3. **Param whitelist stripping**: Strip params not in the generator's
           accepted whitelist. Also corrects the common ``choice`` (singular)
           → ``choices`` (plural) typo.
        """
        gen = col.get("generator")
        if not isinstance(gen, str):
            return

        # Layer 1: Wrap list params as {'choices': [...]} for choice-family generators.
        # LLMs sometimes output params as a bare list (e.g., ['a', 'b', 'c'])
        # instead of a dict. This is a structural format error that would cause
        # TypeError at runtime. Fix it at the source.
        params = col.get("params")
        if gen in _CHOICE_FAMILY_GENERATORS and isinstance(params, list):
            logger.warning(
                "Stage3 Rule #14: wrapping list params as {choices: [...]}",
                column=col.get("name"),
                generator=gen,
                list_length=len(params),
            )
            col["params"] = {"choices": params}
            params = col["params"]

        # Layer 2: Downgrade weighted_choice with string-list choices to choice.
        # weighted_choice expects choices=[{value, weight}, ...] but LLMs often
        # output choices=['a', 'b', 'c'] (string list). Rather than trying to
        # reconstruct weights, downgrade to plain choice which uses the same
        # string-list format. This is semantically equivalent for equal weights.
        if gen == "weighted_choice" and isinstance(params, dict):
            choices = params.get("choices")
            if isinstance(choices, list) and choices and any(isinstance(c, str) for c in choices):
                logger.warning(
                    "Stage3 Rule #14: downgrading weighted_choice to choice "
                    "(choices is string list, not [{value, weight}, ...])",
                    column=col.get("name"),
                    choices=choices,
                )
                col["generator"] = "choice"
                gen = "choice"

        accepted = _GENERATOR_ACCEPTED_PARAMS.get(gen)
        if accepted is None:
            # Unknown generator — leave params alone (let core raise at runtime)
            return
        if not isinstance(params, dict):
            return

        # Layer 3: Common LLM typo: "choice" (singular) should be "choices" (plural)
        # for the "choice" generator. Rename rather than strip.
        if gen == "choice" and "choice" in params and "choices" not in params:
            logger.warning(
                "Stage3 Rule #14: correcting singular 'choice' param to 'choices'",
                column=col.get("name"),
            )
            params["choices"] = params.pop("choice")
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

    def _apply_rule_28_exact_match_upgrade(
        self, col: dict[str, Any], table_schema: dict[str, Any] | None = None
    ) -> None:
        """Rule #28: upgrade generic generators to semantic-specific generators.

        When a column name has an unambiguous semantic mapping (exact-match
        or high-confidence pattern) but the LLM picked a generic generator
        (``string``/``text``/``word``), upgrade to the semantic-specific
        generator. This fixes semantic mismatches like:

          - ``description`` column with ``text`` generator → ``sentence``
            (sentence produces a realistic single-sentence description,
            whereas text produces a multi-paragraph blob that doesn't fit
            typical ``description`` columns)
          - ``email`` column with ``string`` generator → ``email``
            (string produces random alphanumeric, not a valid email)
          - ``title`` column with ``word`` generator → ``sentence``
            (word produces a single random word, not a realistic title)
          - ``product_name`` column with ``word`` generator → ``catch_phrase``
            (word produces a single random word; catch_phrase produces a
            multi-word business phrase, semantically closer to a real
            entity name)

        Only applies when:
          - The column does not have ``derive_from`` set (derived columns
            have no generator to upgrade)
          - LLM-picked generator is in ``_GENERIC_GENERATORS`` (string/text/word)
          - Column name matches an entry in ``_EXACT_MATCH_UPGRADE_RULES``
            (unambiguous exact name) or ``_PATTERN_UPGRADE_RULES``
            (high-confidence pattern)
          - The column is NOT UNIQUE (UNIQUE columns are deferred to
            Rule #24, which upgrades them to template for uniqueness
            guarantee — uniqueness takes priority over semantic matching)

        Respects LLM's non-generic choices: if the LLM picked ``pattern``,
        ``choice``, ``template``, etc., the choice is preserved (those
        generators may reflect domain-specific LLM reasoning).

        Exact-match is checked before pattern-match so the strongest
        semantic signal wins (e.g., ``email`` → ``email`` exact rule, not
        ``.*_email$`` pattern).
        """
        derive_from = col.get("derive_from")
        if derive_from:
            return  # Derived column, no generator to upgrade

        gen = col.get("generator")
        if gen not in _GENERIC_GENERATORS:
            return  # LLM picked a specific generator, respect it

        col_name = col.get("name")
        if not isinstance(col_name, str):
            return

        # Skip UNIQUE columns: Rule #24 (runs later) upgrades them to
        # template for uniqueness guarantee. Rule #28 must not change the
        # generator first, or Rule #24 won't recognize it (Rule #24 only
        # handles word/name/string/integer/uuid).
        constraints = col.get("constraints")
        if isinstance(constraints, dict) and constraints.get("unique"):
            return
        if table_schema:
            unique_cols = table_schema.get("unique_columns", [])
            if isinstance(unique_cols, list) and col_name in unique_cols:
                return

        # 1. Exact-match upgrade (unambiguous column names).
        upgrade = _EXACT_MATCH_UPGRADE_RULES.get(col_name)
        if upgrade is not None:
            new_gen, new_params = upgrade
            logger.warning(
                "Stage3 Rule #28: upgrading generic generator to exact-match",
                column=col_name,
                original_generator=gen,
                upgraded_generator=new_gen,
                reason="column name has unambiguous semantic mapping",
            )
            col["generator"] = new_gen
            if new_params:
                col["params"] = dict(new_params)
            else:
                col.pop("params", None)
            return

        # 2. Pattern-match upgrade (high-confidence patterns mirroring
        # ColumnMapper.PATTERN_MATCH_RULES). Catches semantic mismatches
        # for derived column names like product_name, dept_name, etc.
        for pattern, new_gen, new_params in _PATTERN_UPGRADE_RULES:
            if pattern.match(col_name):
                logger.warning(
                    "Stage3 Rule #28: upgrading generic generator via pattern match",
                    column=col_name,
                    original_generator=gen,
                    upgraded_generator=new_gen,
                    reason="column name matches high-confidence semantic pattern",
                )
                col["generator"] = new_gen
                if new_params:
                    col["params"] = dict(new_params)
                else:
                    col.pop("params", None)
                return

    # ── Rule #29: derive_from integrity (cycles + type compatibility) ──

    # Type families for derive_from compatibility checking.
    _NUMERIC_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "INTEGER",
            "INT",
            "BIGINT",
            "SMALLINT",
            "TINYINT",
            "MEDIUMINT",
            "REAL",
            "FLOAT",
            "DOUBLE",
            "DECIMAL",
            "NUMERIC",
            "NUMBER",
            "INT8",
            "INT16",
            "INT32",
            "INT64",
        }
    )
    _TEXT_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"TEXT", "VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "CLOB", "STRING"}
    )
    _DATE_TYPES: ClassVar[frozenset[str]] = frozenset({"DATE", "DATETIME", "TIMESTAMP", "TIME"})

    def _apply_rule_30_generator_type_compatibility(
        self,
        col: dict[str, Any],
        table_schema: dict[str, Any] | None = None,
    ) -> None:
        """Rule #30: detect and fix severe generator-type mismatches.

        Detects generator-type combinations that cause runtime crashes or
        severe semantic violations:

        1. **Crash: non-date generator on DATE/TIMESTAMP column** — SQLAlchemy's
           DateTime type rejects non-datetime inputs with TypeError. Affected
           generators: integer, float, boolean, string, text, word.
        2. **Crash: date generator on INTEGER/REAL column** — produces date
           objects that SQLAlchemy's numeric types reject.
        3. **Semantic: numeric generator on TEXT column** — float/integer on
           TEXT columns produces numbers where text is expected (e.g.,
           ``product_name`` with ``float`` generator). Downgraded to ``string``
           then Rule #28 is re-attempted for semantic upgrade.
        4. **Crash: text generator on NUMERIC column** — ``text``/``string``/
           ``word`` on INTEGER/REAL columns causes TypeError when the column
           is referenced in a ``derive_from`` arithmetic expression (e.g.,
           ``sale_price = cost_price + random_float(0, cost_price)`` fails
           with ``text + float``). Fixed to type-routed ``float`` (REAL) or
           ``integer`` (INT).

        Runs after Rule #28 (semantic upgrade) so it catches generators that
        Rule #28 didn't upgrade. Runs before Rule #14 (param stripping) so
        invalid params for the new generator are automatically stripped.
        """
        if not table_schema:
            return
        gen = col.get("generator")
        if not isinstance(gen, str):
            return  # Skip null generators (derive_from mode)
        col_name = col.get("name")
        if not isinstance(col_name, str):
            return

        # Find column type from schema
        col_type = ""
        schema_cols = table_schema.get("columns")
        if isinstance(schema_cols, list):
            for ci in schema_cols:
                if isinstance(ci, dict) and ci.get("name") == col_name:
                    col_type = str(ci.get("type", "")).upper()
                    break
        if not col_type:
            return

        # Extract base type token (e.g., "VARCHAR(255)" → "VARCHAR")
        col_base = re.split(r"[(\s]", col_type.strip(), maxsplit=1)[0].upper()

        # Skip derive_from columns — they don't use their generator directly
        derive_from = col.get("derive_from")
        if isinstance(derive_from, list) and derive_from:
            return

        # Determine if generator is incompatible with column type.
        # _ALL_NON_DATE_GENERATORS: everything that produces non-datetime values
        # and would crash on DATE/TIMESTAMP columns.
        needs_fix = False
        fix_reason = ""

        if col_base in self._DATE_TYPES and gen in _ALL_NON_DATE_GENERATORS:
            # Case 1: integer/float/boolean/string/text/word on TIMESTAMP → crash
            needs_fix = True
            fix_reason = "non-date generator on DATE/TIMESTAMP column causes TypeError at insert"
        elif col_base in self._NUMERIC_TYPES and gen in _DATE_GENERATORS:
            # Case 2: date/datetime on INTEGER/REAL → type mismatch
            needs_fix = True
            fix_reason = "date generator on numeric column produces wrong type"
        elif col_base in self._NUMERIC_TYPES and gen in _GENERIC_GENERATORS:
            # Case 4: text/string/word on NUMERIC column → TypeError in derive_from
            # LLMs sometimes assign text generators to numeric columns (e.g.,
            # cost_price REAL gets "text"). This causes derive_from expressions
            # like "value + random_float(0, value)" to fail with TypeError
            # (text + float), and produces nonsensical data even without
            # derive_from. Fix to type-routed float (REAL) or integer (INT).
            needs_fix = True
            fix_reason = "text/string generator on NUMERIC column causes TypeError in derive_from expressions"
        elif col_base in self._TEXT_TYPES and gen in _NUMERIC_BOOLEAN_GENERATORS:
            # Case 3: integer/float on TEXT column → semantic violation
            # (won't crash due to SQLite dynamic typing, but data is wrong).
            # DEFER to Rule #24 Case 3 for code-like columns (_code|_no|sku|serial)
            # and UNIQUE business-id columns (*_id): Rule #24 upgrades them to
            # template, which is a better fix than the generic string fallback.
            # Rule #24 runs later in the pipeline (after Rule #30).
            col_name_lower = col_name.lower()
            is_code_like = bool(re.search(r"(_code|_no|sku|serial)$", col_name_lower))
            # Inline uniqueness check (mirrors Rule #24's logic)
            constraints = col.get("constraints")
            is_unique_constraints = isinstance(constraints, dict) and bool(constraints.get("unique"))
            is_unique_schema = False
            if table_schema:
                unique_cols = table_schema.get("unique_columns", [])
                if isinstance(unique_cols, list) and col_name in unique_cols:
                    is_unique_schema = True
            is_unique = is_unique_constraints or is_unique_schema
            is_business_id = (
                col_name_lower.endswith("_id") and is_unique and not self._is_fk_column(table_schema or {}, col_name)
            )
            if is_code_like or is_business_id:
                return  # Rule #24 Case 3 will handle this
            needs_fix = True
            fix_reason = "numeric generator on TEXT column produces wrong data type"

        if not needs_fix:
            return

        logger.warning(
            "Stage3 Rule #30: fixing severe generator-type mismatch",
            column=col_name,
            column_type=col_base,
            original_generator=gen,
            reason=fix_reason,
        )

        # For TEXT columns with numeric generators, first try Rule #28 semantic
        # upgrade (e.g., product_name → catch_phrase). If Rule #28 upgrades,
        # the column gets a semantically correct generator. If not, fall back
        # to type-routed generator.
        if col_base in self._TEXT_TYPES:
            # Set to generic "string" so Rule #28 can upgrade it
            col["generator"] = "string"
            col.pop("params", None)
            # Re-apply Rule #28 for semantic upgrade
            self._apply_rule_28_exact_match_upgrade(col, table_schema)
            # If Rule #28 didn't upgrade (still "string"), that's fine —
            # string is a valid generator for TEXT columns.
            return

        # For DATE/TIMESTAMP and NUMERIC columns, use type-routed generator
        self._assign_type_routed_generator(col, col_type)

    def _apply_rule_29_derive_from_integrity(self, table: dict[str, Any], table_schema: dict[str, Any]) -> None:
        """Rule #29: detect and break derive_from cycles + type-incompatible derive_from.

        Two problems detected:

        1. **Circular dependencies**: If column A derives from B, and B derives
           from A (directly or transitively), the generation engine cannot
           resolve which column to generate first. This rule breaks cycles by
           removing ``derive_from`` from the column that has a weaker claim:
             - A column NOT participating in a cross-column CHECK is weaker
               (its derive_from was likely LLM-hallucinated, not constraint-driven).
             - If both participate, remove the one whose expression looks like
               a non-arithmetic derivation (e.g., ``catch_phrase`` from a float).

        2. **Type-incompatible derive_from**: A TEXT column deriving from a
           NUMERIC column (or vice versa) produces nonsensical values — you
           cannot compute a realistic product name from a cost_price float.
           This rule strips the derive_from and replaces it with a proper
           generator (Rule #28 semantic matching or type-routed fallback).

        Runs after Rule #27 (which adds derive_from for CHECK-constrained
        columns) and Rule #17 (which strips unsafe DATE derive_from).
        """
        columns = table.get("columns", [])
        if not isinstance(columns, list):
            return

        # Build column config map
        col_map: dict[str, dict[str, Any]] = {}
        for col in columns:
            if isinstance(col, dict) and isinstance(col.get("name"), str):
                col_map[col["name"]] = col

        # Build type map from schema
        col_type_map: dict[str, str] = {}
        schema_cols = table_schema.get("columns")
        if isinstance(schema_cols, list):
            for col_info in schema_cols:
                if isinstance(col_info, dict) and isinstance(col_info.get("name"), str):
                    col_type_map[col_info["name"]] = str(col_info.get("type", "")).upper()

        # Detect derive_from cycles
        self._break_derive_from_cycles(table, col_map, table_schema)

        # Detect type-incompatible derive_from
        for col in list(columns):  # list() to allow mutation
            if not isinstance(col, dict):
                continue
            derive_from = col.get("derive_from")
            if not isinstance(derive_from, list) or not derive_from:
                continue
            col_name = col.get("name")
            if not isinstance(col_name, str):
                continue
            source_name = derive_from[0] if derive_from else None
            if not isinstance(source_name, str):
                continue

            col_type = col_type_map.get(col_name, "")
            source_type = col_type_map.get(source_name, "")

            if self._is_derive_from_type_incompatible(col_type, source_type):
                logger.warning(
                    "Stage3 Rule #29: stripping type-incompatible derive_from",
                    column=col_name,
                    column_type=col_type,
                    source_column=source_name,
                    source_type=source_type,
                    reason="source and target column types are incompatible for derive_from",
                )
                # Strip derive_from and assign a proper generator
                col.pop("derive_from", None)
                col.pop("expression", None)
                # Try Rule #28 semantic matching first
                gen = col.get("generator")
                if gen in _GENERIC_GENERATORS or gen is None:
                    # Apply exact-match or pattern upgrade
                    self._apply_rule_28_exact_match_upgrade(col, table_schema)
                    # If Rule #28 didn't upgrade (e.g., column not in any table),
                    # fall back to type-routed generator
                    if col.get("generator") in _GENERIC_GENERATORS or col.get("generator") is None:
                        self._assign_type_routed_generator(col, col_type)

    def _break_derive_from_cycles(
        self,
        table: dict[str, Any],
        col_map: dict[str, dict[str, Any]],
        table_schema: dict[str, Any],
    ) -> None:
        """Detect and break circular derive_from dependencies.

        Uses DFS cycle detection. When a cycle is found, removes derive_from
        from the column with the weaker claim:
          1. A column NOT participating in a cross-column CHECK is weaker.
          2. If both participate, the column that is the CHECK *source* (right
             side of >=/>/</<=) is weaker — its derive_from should be stripped
             because the CHECK constrains the *target* column (left side),
             which is the one that should derive from the source.
        """
        # Build adjacency list: col -> source col
        adj: dict[str, str | None] = {}
        for name, col in col_map.items():
            derive_from = col.get("derive_from")
            if isinstance(derive_from, list) and len(derive_from) > 0:
                adj[name] = derive_from[0] if isinstance(derive_from[0], str) else None
            else:
                adj[name] = None

        # Find all cycles
        visited: set[str] = set()
        in_stack: set[str] = set()
        cycle_cols: list[str] = []

        def _dfs(node: str) -> bool:
            if node in in_stack:
                # Found a cycle — collect all nodes in this cycle
                cycle_cols.append(node)
                return True
            if node in visited:
                return False
            visited.add(node)
            in_stack.add(node)
            source = adj.get(node)
            if source and source in col_map:
                _dfs(source)
            in_stack.discard(node)
            return False

        for node in adj:
            if node not in visited:
                _dfs(node)

        if not cycle_cols:
            return

        # Determine CHECK source columns (right side of comparison).
        # For "sale_price >= cost_price", cost_price is the CHECK source.
        check_source_cols = self._get_check_source_columns(table_schema)

        # Break cycles: for each cycle column, check if it's the weaker claim
        for col_name in cycle_cols:
            col_cfg = col_map.get(col_name)
            if not isinstance(col_cfg, dict):
                continue
            # Weaker claim: the column is the CHECK *source* (it should NOT
            # derive_from the CHECK *target* — that's backwards)
            if col_name in check_source_cols:
                logger.warning(
                    "Stage3 Rule #29: breaking derive_from cycle — stripping CHECK-source derive_from",
                    column=col_name,
                    original_derive_from=col_cfg.get("derive_from"),
                    reason="column is in derive_from cycle and is CHECK source (should not derive from the target)",
                )
                col_cfg.pop("derive_from", None)
                col_cfg.pop("expression", None)
                # Assign a proper generator (Rule #28 or type-routed)
                gen = col_cfg.get("generator")
                if gen in _GENERIC_GENERATORS or gen is None:
                    self._apply_rule_28_exact_match_upgrade(col_cfg, table_schema)
                if col_cfg.get("generator") in _GENERIC_GENERATORS or col_cfg.get("generator") is None:
                    col_type = ""
                    schema_cols = table_schema.get("columns")
                    if isinstance(schema_cols, list):
                        for ci in schema_cols:
                            if isinstance(ci, dict) and ci.get("name") == col_name:
                                col_type = str(ci.get("type", "")).upper()
                                break
                    self._assign_type_routed_generator(col_cfg, col_type)

    @staticmethod
    def _is_derive_from_type_incompatible(col_type: str, source_type: str) -> bool:
        """Check if derive_from source→target types are incompatible.

        Compatible: numeric→numeric, date→date (same family).
        Incompatible: numeric→text, text→numeric, numeric→date, etc.
        """
        if not col_type or not source_type:
            return False  # Unknown types — don't flag

        # Normalize: extract base type token
        def _base_type(t: str) -> str:
            token = re.split(r"[(\s]", t.strip(), maxsplit=1)[0]
            return token.upper()

        col_base = _base_type(col_type)
        src_base = _base_type(source_type)

        # Cross-family → incompatible
        return not (
            (col_base in Stage3Validator._NUMERIC_TYPES and src_base in Stage3Validator._NUMERIC_TYPES)
            or (col_base in Stage3Validator._TEXT_TYPES and src_base in Stage3Validator._TEXT_TYPES)
            or (col_base in Stage3Validator._DATE_TYPES and src_base in Stage3Validator._DATE_TYPES)
        )

    @staticmethod
    def _get_check_constrained_columns(table_schema: dict[str, Any]) -> set[str]:
        """Get column names that participate in cross-column CHECK constraints."""
        result: set[str] = set()
        checks = table_schema.get("check_constraints", [])
        if not isinstance(checks, list):
            return result
        for check in checks:
            if not isinstance(check, dict):
                continue
            columns = check.get("columns")
            if isinstance(columns, list):
                for c in columns:
                    if isinstance(c, str):
                        result.add(c)
        return result

    @staticmethod
    def _get_check_source_columns(table_schema: dict[str, Any]) -> set[str]:
        """Get columns that are the SOURCE (right side) of cross-column CHECK comparisons.

        For ``sale_price >= cost_price``, cost_price is the CHECK source.
        For ``end_date >= start_date``, start_date is the CHECK source.
        For ``discount <= price``, price is the CHECK source.

        Supports compound CHECK expressions like::
            actual_hours >= 0 AND actual_hours <= est_hours
        where ``est_hours`` is the source (right side of ``<=``).

        These columns should NOT derive_from the CHECK target (left side),
        because the CHECK constrains the target relative to the source.
        """
        result: set[str] = set()
        checks = table_schema.get("check_constraints", [])
        if not isinstance(checks, list):
            return result
        # Get the set of all column names in this table — used to distinguish
        # column references from numeric literals (e.g., "0", "18", "30000").
        schema_cols = table_schema.get("columns")
        col_name_set: set[str] = set()
        if isinstance(schema_cols, list):
            for ci in schema_cols:
                if isinstance(ci, dict) and isinstance(ci.get("name"), str):
                    col_name_set.add(ci["name"])

        for check in checks:
            if not isinstance(check, dict):
                continue
            expr = check.get("expression")
            if not isinstance(expr, str):
                continue
            # Scan the ENTIRE expression (including compound AND/OR clauses) for
            # ``col1 op col2`` patterns. For each match, if the right side is a
            # known column name (not a numeric literal), it is a CHECK source.
            # This handles both simple ("sale_price >= cost_price") and compound
            # ("actual_hours >= 0 AND actual_hours <= est_hours") expressions.
            for m in re.finditer(r"(\w+)\s*(>=|>|<=|<)\s*(\w+)", expr):
                right = m.group(3)
                # Right side is a source column if it's a known column name
                # (not a number). Checking against col_name_set avoids false
                # positives from numeric literals like "0" or "1000".
                if right in col_name_set:
                    result.add(right)
        return result

    @staticmethod
    def _assign_type_routed_generator(col: dict[str, Any], col_type: str) -> None:
        """Assign a type-routed generator based on column SQL type."""
        from sqlseed_ai.staged_analyzer import _GENERATOR_ACCEPTED_PARAMS

        base = re.split(r"[(\s]", col_type.strip(), maxsplit=1)[0].upper()
        if base in {"INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT", "MEDIUMINT", "INT8", "INT16", "INT32", "INT64"}:
            gen_name = "integer"
            params: dict[str, Any] = {"min_value": 1, "max_value": 1000}
        elif base in {"REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "NUMBER"}:
            gen_name = "float"
            params = {"min_value": 0.01, "max_value": 9999.99, "precision": 2}
        elif base in {"TEXT", "VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "CLOB", "STRING"}:
            gen_name = "catch_phrase"
            params = {}
        elif base in {"DATE"}:
            gen_name = "date"
            params = {"start_year": 2000, "end_year": 2024}
        elif base in {"DATETIME", "TIMESTAMP"}:
            gen_name = "datetime"
            params = {"start_year": 2000, "end_year": 2024}
        elif base in {"BOOLEAN", "BOOL"}:
            gen_name = "boolean"
            params = {}
        else:
            gen_name = "string"
            params = {"min_length": 3, "max_length": 20}

        # Strip params not accepted by the generator
        accepted = _GENERATOR_ACCEPTED_PARAMS.get(gen_name, set())
        params = {k: v for k, v in params.items() if k in accepted}

        col["generator"] = gen_name
        if params:
            col["params"] = params
        else:
            col.pop("params", None)

    def _apply_rule_17_boolean_expression(
        self,
        col: dict[str, Any],
        table_schema: dict[str, Any] | None = None,
    ) -> None:
        """Rule #17: detect and correct boolean-comparison derive_from expressions.

        LLMs sometimes return a boolean comparison (e.g. ``sale_price >= value``
        or ``>= value``) instead of an assignment expression. Such expressions
        evaluate to True/False (1/0) at runtime, producing nonsensical data.

        Corrected forms:
          - ``<col> >= value`` or ``>= value``  ->  ``value + random_float(0, value)``
            (ensures the derived value is >= the source value)
          - ``<col> >= 0 AND <col> <= value`` (or similar range)  ->
            ``random_float(0, value)`` (keeps the value within [0, source])
          - Unrecognised boolean expressions  ->  derive_from + expression
            stripped, falling back to a type-routed generator.

        Type-awareness (Rule #17.1): for DATE/DATETIME/TIMESTAMP source columns,
        the ``value + random_float(0, value)`` rewrite is skipped because
        ``float(date)`` raises TypeError at runtime. The derive_from + expression
        are stripped so the column falls back to its type-routed date generator.
        """
        derive_from = col.get("derive_from")
        expression = col.get("expression")
        if not derive_from or not isinstance(expression, str):
            return
        expr = expression.strip()
        col_name = col.get("name", "<unknown>")

        # Type-awareness check: if the source column is a DATE-family type,
        # any rewrite involving random_float/random_int arithmetic would crash
        # at runtime (float(date) raises TypeError). Strip derive_from +
        # expression so the column falls back to its type-routed generator.
        # This takes precedence over all other branches below.
        if (
            isinstance(derive_from, list)
            and len(derive_from) > 0
            and table_schema is not None
            and self._is_date_family_source_column(derive_from[0], table_schema)
        ):
            logger.warning(
                "Stage3 Rule #17: stripping boolean expression for DATE-family source column",
                column=col_name,
                source_column=derive_from[0],
                original=expr,
                reason="float(date) raises TypeError; cannot apply arithmetic rewrite",
            )
            col.pop("derive_from", None)
            col.pop("expression", None)
            return

        # Detect a range comparison like "X >= 0 AND X <= value" or
        # "X >= 0 and X <= value" (case-insensitive).
        # Also matches the reversed order "X <= value AND X >= 0" (LLMs
        # sometimes emit the comparison in reverse, which would otherwise
        # fall through to the fallback branch and strip derive_from entirely).
        range_match = re.match(
            r"^\w+\s*(>=|>)\s*0\s*(?:AND|and)\s*\w+\s*(<=|<)\s*value\s*$",
            expr,
        ) or re.match(
            r"^\w+\s*(<=|<)\s*value\s*(?:AND|and)\s*\w+\s*(>=|>)\s*0\s*$",
            expr,
        )
        if range_match:
            col["expression"] = "random_float(0, value)"
            logger.warning(
                "Stage3 Rule #17: rewriting boolean range expression",
                column=col_name,
                original=expr,
                corrected="random_float(0, value)",
            )
            return

        # Detect "X >= value" or ">= value" (target should be >= source).
        ge_match = re.match(r"^(?:\w+\s*)?>=\s*value\s*$", expr)
        if ge_match:
            col["expression"] = "value + random_float(0, value)"
            logger.warning(
                "Stage3 Rule #17: rewriting boolean '>=' expression",
                column=col_name,
                original=expr,
                corrected="value + random_float(0, value)",
            )
            return

        # Detect "X <= value" or "<= value" (target should be <= source).
        le_match = re.match(r"^(?:\w+\s*)?<=\s*value\s*$", expr)
        if le_match:
            col["expression"] = "random_float(0, value)"
            logger.warning(
                "Stage3 Rule #17: rewriting boolean '<=' expression",
                column=col_name,
                original=expr,
                corrected="random_float(0, value)",
            )
            return

        # Fallback: any other expression containing a comparison operator is
        # likely a boolean comparison — strip derive_from so the column falls
        # back to its generator (type-routed) instead of producing True/False.
        if re.search(r"(>=|<=|==|!=|[^<>]=[^=])", expr) or re.search(r"\b(AND|OR|and|or)\b", expr):
            logger.warning(
                "Stage3 Rule #17: stripping unrecognised boolean derive_from expression",
                column=col_name,
                expression=expr,
            )
            col.pop("derive_from", None)
            col.pop("expression", None)

    @staticmethod
    def _is_date_family_source_column(source_col_name: Any, table_schema: dict[str, Any]) -> bool:
        """Check whether ``source_col_name`` is a DATE/DATETIME/TIMESTAMP column.

        Returns True iff the column type (case-insensitive) is one of:
        DATE, DATETIME, TIMESTAMP, TIME, SMALLDATETIME, DATETIME2.
        """
        if not isinstance(source_col_name, str):
            return False
        columns = table_schema.get("columns")
        if not isinstance(columns, list):
            return False
        for col_info in columns:
            if not isinstance(col_info, dict):
                continue
            if col_info.get("name") != source_col_name:
                continue
            col_type = col_info.get("type")
            if not isinstance(col_type, str):
                continue
            col_type_upper = col_type.upper()
            date_family = {"DATE", "DATETIME", "TIMESTAMP", "TIME", "SMALLDATETIME", "DATETIME2"}
            # Also handle "DATE NOT NULL" / "VARCHAR(255)" / "DATETIME(6)" etc.
            # by extracting the leading type name token.
            type_token = re.split(r"[(\s]", col_type_upper, maxsplit=1)[0]
            return type_token in date_family
        return False

    def _apply_rule_20_sandbox_external_functions(
        self, col: dict[str, Any], table_schema: dict[str, Any] | None = None
    ) -> None:
        """Rule #20: detect sandbox-external functions/identifiers in derive_from expressions.

        LLMs sometimes invent functions like ``floor``, ``random``, ``random_markup``
        that aren't in the simpleeval ``ExpressionEngine.SAFE_FUNCTIONS`` sandbox (only
        ``random_float``/``random_int``/``random_choice`` are exposed). This rule:

          1. Detects and strips **self-referencing derive_from** (e.g.,
             ``sale_price derive_from [sale_price]``) — a column cannot derive
             from itself. Strips derive_from + expression and falls back to a
             type-routed generator.
          2. Attempts pattern-based rewrites for known LLM mistakes
             (e.g. ``floor(random() * (value - N + 1)) + N`` → ``random_int(N, value)``).
          3. If no rewrite matches, scans the expression for unknown identifiers
             (functions or bare names not in the sandbox + context vars). If any
             unknown identifier is found, strips ``derive_from`` + ``expression``
             and assigns a type-routed generator so the column never falls back
             to ``generator: null`` (which would produce NULL values and violate
             NOT NULL / CHECK constraints at insert time).

        This prevents ``FunctionNotDefined`` / ``NameNotDefined`` crashes at runtime
        and ensures stripped columns always have a valid generator.
        """
        derive_from = col.get("derive_from")
        expression = col.get("expression")
        if not derive_from or not isinstance(expression, str):
            return
        expr = expression.strip()
        col_name = col.get("name", "<unknown>")

        # 0. Detect self-referencing derive_from (e.g., sale_price derive_from [sale_price])
        # This is always invalid — a column cannot derive from itself. The LLM
        # sometimes outputs this when confused about CHECK constraints like
        # ``sale_price >= cost_price`` (it tries to make sale_price reference
        # itself instead of cost_price). Strip and fall back to type-routed generator.
        if isinstance(derive_from, list) and col_name in derive_from:
            logger.warning(
                "Stage3 Rule #20: stripping self-referencing derive_from",
                column=col_name,
                derive_from=derive_from,
                reason="a column cannot derive_from itself; falling back to type-routed generator",
            )
            col.pop("derive_from", None)
            col.pop("expression", None)
            self._ensure_fallback_generator(col, col_name, table_schema)
            return

        # 1. Try known pattern rewrites (most common LLM mistakes)
        rewritten = self._try_rewrite_known_sandbox_patterns(expr)
        if rewritten is not None and rewritten != expr:
            logger.warning(
                "Stage3 Rule #20: rewriting sandbox-external function expression",
                column=col_name,
                original=expr,
                corrected=rewritten,
            )
            col["expression"] = rewritten
            return

        # 2. Check for unknown identifiers (functions or bare variable names)
        unknown = self._find_unknown_identifiers(expr)
        if unknown:
            logger.warning(
                "Stage3 Rule #20: stripping expression with sandbox-external identifiers",
                column=col_name,
                expression=expr,
                unknown_identifiers=sorted(unknown),
            )
            col.pop("derive_from", None)
            col.pop("expression", None)
            # Ensure the column has a valid generator after stripping.
            # Without this, the column would have generator: null and produce
            # NULL values at insert time, violating NOT NULL / CHECK constraints.
            self._ensure_fallback_generator(col, col_name, table_schema)

    def _ensure_fallback_generator(
        self,
        col: dict[str, Any],
        col_name: str,
        table_schema: dict[str, Any] | None,
    ) -> None:
        """Ensure a column has a valid generator after derive_from stripping.

        Tries Rule #28 semantic matching first (e.g., ``sale_price`` → no
        exact match → pattern match → no match → type-routed fallback).
        If Rule #28 doesn't upgrade, assigns a type-routed generator based
        on the column's SQL type.
        """
        gen = col.get("generator")
        if gen not in _GENERIC_GENERATORS and gen is not None:
            return  # Already has a non-generic generator
        # Try Rule #28 semantic upgrade first
        self._apply_rule_28_exact_match_upgrade(col, table_schema)
        # If still generic or null, assign type-routed generator
        if col.get("generator") in _GENERIC_GENERATORS or col.get("generator") is None:
            col_type = ""
            if table_schema:
                schema_cols = table_schema.get("columns")
                if isinstance(schema_cols, list):
                    for ci in schema_cols:
                        if isinstance(ci, dict) and ci.get("name") == col_name:
                            col_type = str(ci.get("type", "")).upper()
                            break
            self._assign_type_routed_generator(col, col_type)

    @staticmethod
    def _try_rewrite_known_sandbox_patterns(expr: str) -> str | None:
        """Try to rewrite known LLM patterns that use sandbox-external functions.

        Returns the rewritten expression string, or ``None`` if no known
        pattern matched. Patterns handled (in priority order):

          - ``floor(random() * (value - N + 1)) + N`` → ``random_int(N, value)``
            (reproduces the hr_biz tasks.actual_hours LLM mistake).
          - ``floor(random() * value)`` → ``random_int(0, value)``.
          - ``floor(random() * <int>)`` → ``random_int(0, <int>)``.
          - ``random()`` (standalone) → ``random_float(0, 1)`` (Python's
            ``random.random()`` equivalent).
          - ``random() * (value - N) + N`` → ``random_float(N, value)``.
          - ``random() * value`` → ``random_float(0, value)``.

        Also handles variants where ``value`` is wrapped in ``CAST(value AS REAL)``
        — a common LLM pattern for forcing floating-point arithmetic. The
        CAST wrapper is normalized away before matching (semantically
        equivalent since ``random_float`` already returns REAL).
        """
        # Normalize CAST(value AS REAL) → value (semantically equivalent for
        # our rewrites; the CAST only forces float arithmetic, which
        # random_float/random_int already handle internally).
        normalized = re.sub(
            r"CAST\s*\(\s*value\s+AS\s+REAL\s*\)",
            "value",
            expr,
            flags=re.IGNORECASE,
        )
        # If normalization changed the expression, recurse on the normalized
        # form so all existing patterns apply to CAST variants too.
        if normalized != expr:
            result = Stage3Validator._try_rewrite_known_sandbox_patterns(normalized)
            if result is not None:
                return result

        # Pattern: floor(random() * (value - N + 1)) + N  →  random_int(N, value)
        # The offset N appears twice; if they differ, take the larger (offset).
        m = re.match(
            r"^floor\(random\(\)\s*\*\s*\(value\s*-\s*(-?\d+)\s*\+\s*1\)\)\s*\+\s*(-?\d+)$",
            expr,
        )
        if m:
            n1, n2 = int(m.group(1)), int(m.group(2))
            offset = n1 if n1 == n2 else max(n1, n2)
            return f"random_int({offset}, value)"

        # Pattern: floor(random() * (value - N) + N)  →  random_int(N, value)
        # LLM pattern for "random integer in [N, value)" (e.g., actual_hours
        # in [0, est_hours)). Handles N=0 (no offset) and positive N.
        # Differs from the +1 pattern above: no "+1" inside the inner paren,
        # and the trailing "+N" is INSIDE the floor() call, not outside.
        m = re.match(
            r"^floor\(random\(\)\s*\*\s*\(value\s*-\s*(-?\d+(?:\.\d+)?)\)\s*\+\s*(-?\d+(?:\.\d+)?)\)$",
            expr,
        )
        if m:
            o1, o2 = m.group(1), m.group(2)
            # If both offsets match, use it; otherwise take the larger (lower bound
            # for random_int is the offset since floor(random()*range)+offset).
            offset_val: float = float(o1) if o1 == o2 else max(float(o1), float(o2))
            offset_str = str(int(offset_val)) if offset_val == int(offset_val) else str(offset_val)
            return f"random_int({offset_str}, value)"

        # Pattern: floor(random() * value)  →  random_int(0, value)
        if re.match(r"^floor\(random\(\)\s*\*\s*value\)$", expr):
            return "random_int(0, value)"

        # Pattern: floor(random() * <int>)  →  random_int(0, <int>)
        m = re.match(r"^floor\(random\(\)\s*\*\s*(\d+)\)$", expr)
        if m:
            return f"random_int(0, {m.group(1)})"

        # Pattern: random() (standalone, exact match)  →  random_float(0, 1)
        if expr == "random()":
            return "random_float(0, 1)"

        # Pattern: random() * (value - N) + N  →  random_float(N, value)
        # Common LLM pattern for "random value in [N, value]" (e.g., discount
        # in [0, price_per_unit]). Handles N=0 (no offset) and positive N.
        m = re.match(
            r"^random\(\)\s*\*\s*\(value\s*-\s*(-?\d+(?:\.\d+)?)\)\s*\+\s*(-?\d+(?:\.\d+)?)$",
            expr,
        )
        if m:
            o1, o2 = m.group(1), m.group(2)
            # If both offsets match, use it; otherwise take the smaller (lower bound).
            lo_val: float = float(o1) if o1 == o2 else min(float(o1), float(o2))
            # Preserve int formatting when possible (avoids "0.0" in expressions).
            lo_str = str(int(lo_val)) if lo_val == int(lo_val) else str(lo_val)
            return f"random_float({lo_str}, value)"

        # Pattern: random() * value  →  random_float(0, value)
        # LLM pattern for "random fraction of value" (e.g., discount = random * price).
        if re.match(r"^random\(\)\s*\*\s*value$", expr):
            return "random_float(0, value)"

        return None

    @staticmethod
    def _find_unknown_identifiers(expr: str) -> set[str]:
        """Find identifiers in expression that aren't in the sandbox or context.

        Returns a set of unknown identifier names (functions or bare variable
        references). Known-safe identifiers are filtered out:

          - ``ExpressionEngine.SAFE_FUNCTIONS`` keys (25 functions).
          - Context vars: ``value``, ``row``.
          - Python constants: ``True``, ``False``, ``None``.
          - Python keywords: ``and``, ``or``, ``not``, ``if``, ``else``,
            ``for``, ``in``, ``is``.
        """
        # Lazy import to avoid hard dependency at module import time
        from sqlseed.core.expression import ExpressionEngine

        safe_names = set(ExpressionEngine.SAFE_FUNCTIONS.keys())
        allowed = safe_names | {
            "value",
            "row",  # context vars
            "True",
            "False",
            "None",  # Python constants
            "and",
            "or",
            "not",
            "if",
            "else",
            "for",
            "in",
            "is",  # keywords
        }
        # Match all identifier-like tokens (letters/digits/underscore, starting with letter/_)
        tokens = set(re.findall(r"\b[a-zA-Z_]\w*\b", expr))
        # Filter out allowed identifiers
        return {token for token in tokens if token not in allowed}

    def _apply_rule_26_int_column_float_to_int(
        self,
        col: dict[str, Any],
        table_schema: dict[str, Any] | None,
    ) -> None:
        """Rule #26: coerce ``random_float`` to ``random_int`` for INTEGER columns.

        LLMs sometimes return ``random_float(0, value)`` for INTEGER columns
        (e.g., ``tasks.actual_hours INTEGER``). SQLite's dynamic typing allows
        storing fractional values in an INTEGER column, but the result is
        semantically wrong (e.g., 25.57 hours is not a meaningful integer
        hour count). This rule rewrites ``random_float(...)`` to
        ``random_int(...)`` when the target column is INTEGER-family.

        Skips:
          - Columns without ``derive_from`` + ``expression`` (no expression
            to rewrite).
          - Columns whose schema type is not INTEGER-family (REAL/FLOAT/
            DOUBLE/NUMERIC/DECIMAL/TEXT all keep ``random_float``).
          - Expressions that do not contain ``random_float(`` (no-op).
        """
        derive_from = col.get("derive_from")
        expression = col.get("expression")
        if not derive_from or not isinstance(expression, str):
            return
        if table_schema is None:
            return
        col_name = col.get("name")
        if not isinstance(col_name, str):
            return
        col_type = self._get_column_type_from_schema(table_schema, col_name)
        if not col_type or not self._is_integer_type(col_type):
            return
        expr = expression.strip()
        if "random_float(" not in expr:
            return
        new_expr = expr.replace("random_float(", "random_int(")
        logger.warning(
            "Stage3 Rule #26: coercing random_float to random_int for INTEGER column",
            column=col_name,
            column_type=col_type,
            original=expr,
            corrected=new_expr,
            reason="INTEGER column should not store fractional values",
        )
        col["expression"] = new_expr

    def _apply_rule_27_missing_generator_with_check_inference(
        self, table: dict[str, Any], table_schema: dict[str, Any]
    ) -> None:
        """Rule #27: fill missing generators + infer derive_from from cross-column CHECKs.

        Two scenarios:

        1. **Column missing generator + participates in cross-column CHECK where
           the OTHER column has a generator**: infer ``derive_from`` + ``expression``
           from the CHECK constraint so the derived value automatically satisfies
           it. Example: ``CHECK (sale_price >= cost_price)`` on a ``sale_price``
           column with no generator (but ``cost_price`` has one) →
           ``derive_from: [cost_price]``,
           ``expression: "value + random_float(0, value)"`` (ensures
           ``sale_price >= cost_price``).

        2. **Column missing generator + no usable cross-column CHECK**: fall
           back to a type-routed generator based on the column's SQL type
           (INTEGER → integer, REAL → float, DATE → date with default year
           range, etc.). The date/datetime fallback includes default
           ``start_year``/``end_year`` params so Rule #22 can subsequently
           isolate ranges if the column participates in a cross-column date
           CHECK.

        This rule runs FIRST (before Rule #14-#26) so subsequent rules can
        process the supplemented columns normally.

        Skips:
          - Columns that already have a generator (``generator`` is not None)
          - Columns with ``derive_from`` already set (derived mode, no
            generator needed)
        """
        checks = table_schema.get("check_constraints", [])
        if not isinstance(checks, list):
            checks = []

        # Build column config map for quick lookup
        col_configs: dict[str, dict[str, Any]] = {}
        for col in table.get("columns", []):
            if isinstance(col, dict) and isinstance(col.get("name"), str):
                col_configs[col["name"]] = col

        # Snapshot of columns that ORIGINALLY had a generator (before Rule #27
        # fills any). This prevents ordering-dependent derive_from chains where
        # col_b derives from col_a after col_a was filled by Rule #27's
        # type-routed fallback — deriving from a random fallback value has no
        # semantic meaning and would produce meaningless derived data.
        original_has_generator: dict[str, bool] = {
            name: cfg.get("generator") is not None for name, cfg in col_configs.items()
        }

        # Build column type map for type-routed fallback
        col_type_map: dict[str, str] = {}
        for col_info in table_schema.get("columns", []):
            if isinstance(col_info, dict):
                name = col_info.get("name")
                col_type = col_info.get("type")
                if isinstance(name, str) and isinstance(col_type, str):
                    col_type_map[name] = col_type

        for col in table.get("columns", []):
            if not isinstance(col, dict):
                continue
            # Skip columns that already have a generator or derive_from
            if col.get("generator") is not None:
                continue
            if col.get("derive_from"):
                continue

            col_name = col.get("name")
            if not isinstance(col_name, str):
                continue

            # Scenario 1: try to infer derive_from from cross-column CHECK.
            # Only derive from columns that ORIGINALLY had a generator —
            # deriving from a Rule #27-filled fallback would be meaningless.
            inferred = self._try_infer_derive_from_check(col_name, checks, col_configs, original_has_generator)
            if inferred is not None:
                source_col, expression = inferred
                col["derive_from"] = [source_col]
                col["expression"] = expression
                logger.warning(
                    "Stage3 Rule #27: inferred derive_from from cross-column CHECK",
                    column=col_name,
                    source_column=source_col,
                    expression=expression,
                )
                continue

            # Scenario 2: fall back to type-routed generator
            col_type = col_type_map.get(col_name, "")
            type_routed = self._build_type_routed_for_missing(col_type)
            col["generator"] = type_routed["generator"]
            col["params"] = type_routed["params"]
            logger.warning(
                "Stage3 Rule #27: supplemented missing generator with type-routed fallback",
                column=col_name,
                column_type=col_type,
                generator=type_routed["generator"],
            )

    def _try_infer_derive_from_check(
        self,
        target_col: str,
        checks: list[Any],
        col_configs: dict[str, dict[str, Any]],
        original_has_generator: dict[str, bool] | None = None,
    ) -> tuple[str, str] | None:
        """Try to infer ``derive_from`` + ``expression`` from cross-column CHECK.

        Searches CHECK constraints for comparisons involving ``target_col``.
        If the OTHER column in the comparison originally had a generator
        (i.e., was not also missing — checked via ``original_has_generator``
        snapshot to avoid ordering-dependent derive chains), returns
        ``(other_col, expression)`` where ``expression`` is built to
        satisfy the comparison.

        Returns ``None`` if:
          - No cross-column CHECK involves ``target_col``
          - The other column also originally had no generator (cannot derive
            from a Rule #27-filled fallback)
          - The CHECK expression is too complex to parse
          - The comparison operator is not recognised
        """
        for check in checks:
            if not isinstance(check, dict):
                continue
            expr = check.get("expression")
            if not isinstance(expr, str):
                continue
            parsed = self._parse_cross_column_numeric_comparison(expr)
            if parsed is None:
                continue
            col_a, op, col_b = parsed

            # Determine which is target, which is source
            if col_a == target_col:
                source_col = col_b
                # CHECK: target_col op source_col → target must satisfy (target op source)
                expression = self._build_check_satisfying_expression(op)
            elif col_b == target_col:
                source_col = col_a
                # CHECK: source_col op target_col → target must satisfy (source op target)
                # Reverse the operator: if CHECK is source >= target, then target <= source
                reverse_op = self._reverse_operator(op)
                if reverse_op is None:
                    continue
                expression = self._build_check_satisfying_expression(reverse_op)
            else:
                continue

            if expression is None:
                continue

            # Source column must have ORIGINALLY had a generator (not also
            # missing). Using the pre-Rule-27 snapshot prevents ordering-
            # dependent derive chains where col_b derives from col_a after
            # col_a was filled by Rule #27's type-routed fallback.
            if original_has_generator is not None:
                if not original_has_generator.get(source_col, False):
                    continue  # Source also originally missing, cannot derive
            else:
                # Fallback for backward compat (no snapshot provided)
                source_config = col_configs.get(source_col)
                if not isinstance(source_config, dict):
                    continue
                if source_config.get("generator") is None:
                    continue  # Source also missing, cannot derive

            return (source_col, expression)

        return None

    @staticmethod
    def _parse_cross_column_numeric_comparison(expr: str) -> tuple[str, str, str] | None:
        """Parse a cross-column numeric comparison CHECK expression.

        Recognised patterns (case-insensitive operator, whitespace-tolerant):
          - ``<col_a> (>=|>|<=|<) <col_b>`` → ``(col_a, op, col_b)``

        Returns:
            ``(col_a, operator, col_b)`` if the expression matches, else ``None``.
            Both sides must be word characters (letters/digits/underscore) —
            numeric literals or complex expressions are rejected.

        Note: This is distinct from ``_parse_cross_column_date_comparison``
        (used by Rule #22) — that method returns ``(later_col, earlier_col)``
        for date-range isolation, while this method returns the raw triple
        for numeric derive_from inference.
        """
        expr_stripped = expr.strip()
        m = re.match(r"^\s*(\w+)\s*(>=|>|<=|<)\s*(\w+)\s*$", expr_stripped)
        if not m:
            return None
        col_a, op, col_b = m.groups()
        # Reject if either side looks like a number
        if col_a.isdigit() or col_b.isdigit():
            return None
        return (col_a, op, col_b)

    @staticmethod
    def _reverse_operator(op: str) -> str | None:
        """Reverse a comparison operator for swapped target/source positions.

        If CHECK is ``source op target``, then target must satisfy
        ``target reverse_op source``:

          - ``>=`` → ``<=`` (source >= target ⟺ target <= source)
          - ``>``  → ``<``  (source > target  ⟺ target < source)
          - ``<=`` → ``>=`` (source <= target ⟺ target >= source)
          - ``<``  → ``>``  (source < target  ⟺ target > source)
        """
        return {">=": "<=", ">": "<", "<=": ">=", "<": ">"}.get(op)

    @staticmethod
    def _build_check_satisfying_expression(op: str) -> str | None:
        """Build a derive_from expression that satisfies ``target op source``.

        The ``value`` placeholder refers to the source column's value (injected
        by the ExpressionEngine context when ``derive_from`` is set).

          - ``>=`` → ``value + random_float(0, value)`` (target in [source, 2*source])
          - ``>``  → ``value + random_float(1, value)`` (target in (source, 2*source])
          - ``<=`` → ``random_float(0, value)`` (target in [0, source])
          - ``<``  → ``random_float(0, max(value - 1, 0))`` (target in [0, source))

        All functions (``random_float``, ``max``) are in
        ``ExpressionEngine.SAFE_FUNCTIONS``, so the expression is
        sandbox-safe and will not be stripped by Rule #20.
        """
        if op == ">=":
            return "value + random_float(0, value)"
        if op == ">":
            return "value + random_float(1, value)"
        if op == "<=":
            return "random_float(0, value)"
        if op == "<":
            return "random_float(0, max(value - 1, 0))"
        return None

    @staticmethod
    def _build_type_routed_for_missing(col_type: str) -> dict[str, Any]:
        """Build type-routed generator config for a missing-generator column.

        Mirrors ``StagedSchemaAnalyzer._degrade_to_type_routed`` but accepts
        a type string instead of ``ColumnFeatures``, and adds default
        year-range params for date/datetime so Rule #22 can subsequently
        isolate ranges if the column participates in a cross-column date CHECK.
        """
        type_upper = col_type.upper()
        if "INT" in type_upper:
            return {"generator": "integer", "params": {"min_value": 0, "max_value": 99999}}
        if any(t in type_upper for t in ("REAL", "FLOAT", "DOUBLE", "DECIMAL")):
            return {"generator": "float", "params": {"min_value": 0.0, "max_value": 9999.0}}
        if "BOOL" in type_upper:
            return {"generator": "boolean", "params": {}}
        if "DATE" in type_upper and "TIME" not in type_upper:
            # Default year range so Rule #22 can isolate if needed
            return {"generator": "date", "params": {"start_year": 2000, "end_year": 2024}}
        if any(t in type_upper for t in ("DATETIME", "TIMESTAMP")):
            return {"generator": "datetime", "params": {"start_year": 2000, "end_year": 2024}}
        return {"generator": "string", "params": {"min_length": 1, "max_length": 100}}

    def _apply_rule_16_fk_semantic(self, table: dict[str, Any], table_schema: dict[str, Any]) -> None:
        """Rule #16: FK columns must use a generator compatible with ref column type.

        Currently only checks: FK to integer column must use integer generator
        (common LLM mistake: assigning username/name to FK columns ending in _by).

        Skips columns that already have ``derive_from`` set — derive_from takes
        precedence over generator (enforced by Fix 1 in rules #1-#13), so adding
        a generator back here would re-introduce the mutual-exclusivity clash
        that Pydantic rejects (``cannot use both 'generator' and 'derive_from'``).
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
            # derive_from takes precedence — do not re-add generator+params
            # (would clash with derive_from and break Pydantic validation).
            if col.get("derive_from"):
                continue
            gen = col.get("generator")
            # Integer-compatible generators
            if gen in ("integer", "uuid", "pattern"):
                # Even for integer FKs, cap an unreasonably large max_value
                # (LLMs sometimes return 10^9). Test datasets rarely exceed
                # 1000 parent rows, so cap at 1000 to keep FKs resolvable.
                self._cap_fk_max_value(col, col_name)
                continue
            logger.warning(
                "Stage3 Rule #16: replacing string generator on integer FK column",
                column=col_name,
                original_generator=gen,
                ref_column_type="integer",
            )
            col["generator"] = "integer"
            col["params"] = {"min_value": 1, "max_value": 1000}

    @staticmethod
    def _cap_fk_max_value(col: dict[str, Any], col_name: Any) -> None:
        """Cap an unreasonably large FK ``max_value`` to 1000 and ensure ``min_value`` is set.

        LLMs sometimes return ``max_value`` like 10^9 for FK columns, which
        produces orphan FKs (the referenced parent table typically has far
        fewer rows). Capping at 1000 keeps generated FKs resolvable in
        typical test datasets (100-1000 rows per table).

        Also ensures ``min_value=1`` is set when missing — parent rows
        always start at id=1 (autoincrement), so a FK value of 0 would
        always be an orphan. LLMs sometimes omit ``min_value`` entirely
        (e.g., ``tasks.assignee_id`` had only ``max_value: 1000``), which
        lets the integer generator produce 0 (and negative values via the
        default ``min_value=0``), producing orphan FKs.

        Also raises ``max_value`` if too low (< 100) — LLMs sometimes
        confuse FK columns with CHECK-constrained columns in the same table
        (e.g., ``order_items.product_id`` got ``max_value: 5`` because the
        LLM confused it with ``quantity CHECK(quantity <= 5)``). FK columns
        should reference a reasonable range of parent rows (1000 by default)
        to produce realistic test data.
        """
        params = col.get("params")
        if not isinstance(params, dict):
            return
        max_val = params.get("max_value")
        if isinstance(max_val, (int, float)) and max_val > 1000:
            logger.warning(
                "Stage3 Rule #16: capping unreasonably large FK max_value",
                column=col_name,
                original_max_value=max_val,
                capped_max_value=1000,
            )
            params["max_value"] = 1000
        elif isinstance(max_val, (int, float)) and max_val < 100:
            # LLM likely confused FK column with a CHECK-constrained sibling.
            # Raise to 1000 so FK references a reasonable range of parent rows.
            logger.warning(
                "Stage3 Rule #16: raising too-low FK max_value to 1000",
                column=col_name,
                original_max_value=max_val,
                raised_max_value=1000,
                reason="FK column max_value < 100 likely confused with CHECK-constrained sibling",
            )
            params["max_value"] = 1000
        # Ensure min_value=1 for FK columns (parent rows start at id=1).
        # Without this, integer generator defaults min_value=0 and produces
        # orphan FKs (id=0 never exists in the parent table).
        min_val = params.get("min_value")
        if not isinstance(min_val, (int, float)):
            logger.warning(
                "Stage3 Rule #16: setting missing FK min_value to 1",
                column=col_name,
            )
            params["min_value"] = 1
        elif isinstance(min_val, (int, float)) and min_val < 1:
            # Negative or zero min_value would produce orphan FKs.
            logger.warning(
                "Stage3 Rule #16: raising FK min_value from below-1 to 1",
                column=col_name,
                original_min_value=min_val,
            )
            params["min_value"] = 1

    def _apply_rule_18_cap_future_end_year(self, col: dict[str, Any]) -> None:
        """Rule #18: cap unreasonable future ``end_year`` on date/datetime generators.

        LLMs sometimes return ``end_year: 2100`` (or similar far-future values),
        producing test data with dates in the 2090s. Test datasets should use
        realistic past/current dates, so cap ``end_year`` at ``current_year + 1``
        (allows a small lookahead for expiry-style columns without producing
        22nd-century data).

        Only applies to ``date`` and ``datetime`` generators (``timestamp``
        accepts no params and uses the default range internally).
        """
        gen = col.get("generator")
        if gen not in ("date", "datetime"):
            return
        params = col.get("params")
        if not isinstance(params, dict):
            return
        end_year = params.get("end_year")
        if not isinstance(end_year, int):
            return
        cap = datetime.now().year + 1
        if end_year > cap:
            logger.warning(
                "Stage3 Rule #18: capping unreasonable future end_year",
                column=col.get("name"),
                original_end_year=end_year,
                capped_end_year=cap,
            )
            params["end_year"] = cap

    def _apply_rule_23_phone_to_pattern(self, col: dict[str, Any]) -> None:
        """Rule #23: upgrade phone-like columns to a realistic NANP pattern.

        The Faker ``phone`` generator emits mixed formats across rows (e.g.,
        ``+1 (555) 123-4567`` vs ``555-123-4567`` vs ``(555) 123.4567``). Real
        front-end validation (and many DB schemas with CHECK constraints) expect
        a single consistent format. Upgrading to ``pattern`` with a strict NANP
        regex guarantees every row has the same shape AND realistic digits.

        NANP format: ``^\\+1-[2-9]\\d{2}-[2-9]\\d{2}-\\d{4}$``
          - Country code ``+1``
          - Area code ``[2-9]\\d{2}`` (200-999; NANP area codes cannot start with 0/1)
          - Exchange ``[2-9]\\d{2}`` (200-999; exchanges cannot start with 0/1)
          - Subscriber ``\\d{4}`` (any 4 digits)

        Three cases trigger on phone-like column names (``phone``, ``mobile``,
        ``telephone``, ``tel``, ``cell``, ``cellphone``, ``contact_number``,
        ``*_phone``, ``*_mobile``, etc.):

          - Case 1: bare ``phone`` generator (no params) → upgrade to NANP pattern
          - Case 2: ``pattern`` generator with simple all-digits regex
            (e.g., ``^\\d{3}-\\d{3}-\\d{4}$``) → upgrade regex to NANP
          - Case 3: ``string`` generator on phone column → upgrade to NANP pattern

        A ``phone`` generator with explicit params (rare, but possible from the
        LLM) is left alone. A pattern that already enforces NANP rules
        (contains ``[2-9]``) is also left alone.
        """
        col_name = col.get("name")
        if not isinstance(col_name, str):
            return
        if not self._is_phone_like_column(col_name):
            return

        gen = col.get("generator")
        nanp_regex = r"^\+1-[2-9]\d{2}-[2-9]\d{2}-\d{4}$"

        # Case 1: bare phone generator → upgrade to NANP pattern
        if gen == "phone":
            params = col.get("params")
            if params and len(params) > 0:
                return  # LLM explicitly set params, leave alone
            logger.warning(
                "Stage3 Rule #23: upgrading bare phone generator to NANP pattern",
                column=col_name,
            )
            col["generator"] = "pattern"
            col["params"] = {"regex": nanp_regex}
            return

        # Case 2: pattern with simple all-digits regex → upgrade to NANP
        if gen == "pattern":
            params = col.get("params")
            if not isinstance(params, dict):
                return
            regex = params.get("regex") or params.get("pattern")
            if not isinstance(regex, str):
                return
            # Already realistic (has [2-9] prefix)? Leave alone.
            if "[2-9]" in regex:
                return
            # Only upgrade simple all-digits patterns (e.g., ^\d{3}-\d{3}-\d{4}$)
            # Match patterns containing \d (digit class) or [0-9]
            if re.search(r"\\d|\[0-9\]", regex):
                logger.warning(
                    "Stage3 Rule #23: upgrading simple phone pattern to NANP",
                    column=col_name,
                    old_regex=regex,
                )
                col["params"] = {"regex": nanp_regex}
            return

        # Case 3: string generator on phone column → upgrade to NANP pattern
        if gen == "string":
            logger.warning(
                "Stage3 Rule #23: upgrading string generator on phone column to NANP pattern",
                column=col_name,
            )
            col["generator"] = "pattern"
            col["params"] = {"regex": nanp_regex}
            return

    @staticmethod
    def _is_phone_like_column(col_name: str) -> bool:
        """Detect phone-like column names (case-insensitive).

        Matches exact names: ``phone``, ``mobile``, ``telephone``, ``tel``,
        ``cell``, ``cellphone``, ``contact_number``.

        Matches suffixes: ``*_phone``, ``*_mobile``, ``*_telephone``,
        ``*_tel``, ``*_cell``, ``*_cellphone``, ``*_contact_number``.
        """
        name_lower = col_name.lower()
        phone_words = {
            "phone",
            "mobile",
            "telephone",
            "tel",
            "cell",
            "cellphone",
            "contact_number",
        }
        if name_lower in phone_words:
            return True
        return any(name_lower.endswith("_" + word) for word in phone_words)

    def _apply_rule_25_text_to_string_for_codes(self, col: dict[str, Any]) -> None:
        """Rule #25: convert ``text`` generator to ``string`` on code-like columns.

        Plugin-layer workaround for a core ``ColumnMapper`` param-merge bug
        (``mapper.py`` "Group Merge Compatibility", lines ~377-402). When the
        LLM returns ``text`` for a code-like column (e.g., ``sku``, ``item_code``)
        and the mapper's exact-match rule has ``string`` with ``charset``
        (e.g., ``sku`` → ``string`` with ``charset: alphanumeric``), both
        generators fall into ``string_generators = {"string", "text", "sentence"}``
        and the merge puts ``charset`` into the ``text`` params. But
        ``_gen_text`` does NOT accept ``charset``, so generation crashes with
        ``MimesisProvider._gen_text() got an unexpected keyword argument
        'charset'``.

        Code-like columns (``_code|_no|sku|serial``) are short identifiers,
        not free-form text — semantically they should use ``string`` (which
        accepts ``charset`` to enforce alphanumeric-only, matching real-world
        SKU/code formats used in barcodes, URLs, and joins).

        Converting ``text`` → ``string`` here ensures:
          1. The mapper merge keeps both generators in the same group
             (``string`` == ``string``), so ``charset`` from the exact-match
             rule correctly applies.
          2. ``_gen_string`` accepts ``charset``, so no crash.
          3. Downstream Rule #24 Case 2 can upgrade the ``string`` to
             ``template`` when UNIQUE is required.

        Only converts when ``generator == "text"`` AND column name matches
        ``_code|_no|sku|serial`` pattern. Preserves user-supplied params
        (``min_length``/``max_length``); the mapper will merge ``charset``
        from the exact-match rule at fill time.
        """
        gen = col.get("generator")
        if gen != "text":
            return
        col_name = col.get("name")
        if not isinstance(col_name, str):
            return
        col_name_lower = col_name.lower()
        # Same code-like pattern used by Rule #24 Case 2/3.
        if not re.search(r"(_code|_no|sku|serial)$", col_name_lower):
            return
        logger.warning(
            "Stage3 Rule #25: converting text generator to string on code-like column",
            column=col_name,
            reason=(
                "text generator cannot accept charset param from mapper merge; "
                "string is the correct generator for short alphanumeric identifiers"
            ),
        )
        col["generator"] = "string"
        # Keep existing params (min_length/max_length). The mapper will merge
        # charset from the exact-match rule at fill time.

    def _apply_rule_24_unique_word_to_template(
        self, col: dict[str, Any], table_schema: dict[str, Any] | None = None
    ) -> None:
        """Rule #24: upgrade weak/incorrect generators on code/name/id columns to ``template``.

        The English lexicon has only a few hundred common words; Faker's
        ``word`` generator cannot satisfy a UNIQUE constraint over 1000+ rows.
        Similarly, ``name`` (real person names) saturates quickly on large
        tables. Upgrading to a templated value with ``{sequence:04d}`` guarantees
        uniqueness without sacrificing readability.

        Four cases (UNIQUE flag detected from ``col["constraints"]`` OR
        ``table_schema["unique_columns"]``):

          - Case 1 (UNIQUE required): generator is ``word``/``name`` → upgrade
            to ``{gen}{sequence:04d}`` (preserves original gen name as prefix).
          - Case 2 (UNIQUE required): generator is ``string`` AND column name
            matches ``_code|_no|sku|serial`` pattern → upgrade to
            ``{PREFIX}-{sequence:04d}`` (random strings offer no uniqueness
            guarantee on 1000+ rows).
          - Case 3 (UNIQUE NOT required): generator is ``integer`` AND column
            type is TEXT family AND name matches ``_code|_no|sku|serial``
            pattern → upgrade to ``{PREFIX}-{sequence:04d}`` (type mismatch
            fix: LLM generated integer for a TEXT code column — this is a
            data-quality bug regardless of uniqueness constraints).
          - Case 4 (UNIQUE required): generator is ``uuid`` AND column name
            matches ``_id$`` (and is not literally ``uuid``/``guid``/``token``)
            → upgrade to ``{PREFIX}-{sequence:04d}`` (readable business ID
            like ``EMPL-0001`` instead of ``550e8400-e29b-41d4-...``).
            Random UUIDs are unreadable in HR/business contexts and
            inconsistent with sibling ``*_code``/``*_no`` columns.
          - Case 5 (UNIQUE required): generator is ``choice``/``weighted_choice``
            AND column name matches ``_code|_no|sku|serial`` pattern → upgrade
            to ``{PREFIX}-{sequence:04d}``. LLMs sometimes confuse code columns
            with status columns (e.g., ``merchant_code`` gets
            ``choice: [active, suspended, closed]`` instead of ``MERC-0001``).
            A low-cardinality choice generator cannot satisfy a UNIQUE
            constraint over 1000+ rows.

        ``template``/``pattern`` columns are skipped (already safe).

        Case 6 (UNIQUE required): generator is ``date``/``timestamp``/``datetime``
        AND column name matches ``_code|_no|sku|serial`` pattern → upgrade to
        ``{PREFIX}-{sequence:04d}``. LLMs sometimes misclassify code columns
        as date columns (e.g., ``project_code`` gets ``date`` generator
        producing "2021-10-24" instead of "PROJ-0001"). Date values on a
        code-like column are a semantic error even if they happen to be
        unique (business codes must be readable identifiers).
        """
        gen = col.get("generator")
        if gen in ("template", "pattern", None):
            return  # Already safe or derived mode (None means derived)
        if gen not in (
            "word",
            "name",
            "string",
            "integer",
            "uuid",
            "choice",
            "weighted_choice",
            "date",
            "timestamp",
            "datetime",
        ):
            return

        col_name = col.get("name")
        if not isinstance(col_name, str):
            return
        col_name_lower = col_name.lower()

        # Determine UNIQUE from col constraints
        constraints = col.get("constraints")
        is_unique_constraints = isinstance(constraints, dict) and bool(constraints.get("unique"))

        # Determine UNIQUE from schema (LLM may have omitted the constraints field)
        is_unique_schema = False
        if table_schema:
            unique_cols = table_schema.get("unique_columns", [])
            if isinstance(unique_cols, list) and col_name in unique_cols:
                is_unique_schema = True

        is_unique = is_unique_constraints or is_unique_schema

        # Case 1: UNIQUE word/name → upgrade to template (preserve gen name as prefix)
        if is_unique and gen in ("word", "name"):
            logger.warning(
                "Stage3 Rule #24: upgrading UNIQUE word/name generator to template",
                column=col_name,
                original_generator=gen,
            )
            col["generator"] = "template"
            col.pop("params", None)
            col["params"] = {"template": f"{gen}{{sequence:04d}}"}
            return

        # Cases 2/3 only apply to code-like column names
        is_code_like = bool(re.search(r"(_code|_no|sku|serial)$", col_name_lower))

        # Case 2: UNIQUE string + code-like name → upgrade to template
        if is_unique and gen == "string" and is_code_like:
            prefix = self._derive_code_template_prefix(col_name)
            logger.warning(
                "Stage3 Rule #24: upgrading UNIQUE string code column to template",
                column=col_name,
                original_generator=gen,
                template_prefix=prefix,
            )
            col["generator"] = "template"
            col.pop("params", None)
            col["params"] = {"template": f"{prefix}{{sequence:04d}}"}
            return

        # Case 3: integer generator on TEXT code/id column → type mismatch fix.
        # LLMs sometimes generate `integer` for TEXT NOT NULL UNIQUE code columns
        # (e.g., task_no TEXT NOT NULL UNIQUE with integer generator). Upgrading
        # to template fixes both the type mismatch and the uniqueness guarantee.
        # Extended to also handle *_id columns (e.g., employee_id TEXT NOT NULL
        # UNIQUE with integer generator) when the column is NOT a FK — FK columns
        # like dept_id INTEGER are correctly integer and must not be upgraded.
        if gen == "integer" and table_schema:
            col_type = self._get_column_type_from_schema(table_schema, col_name)
            if col_type and self._is_text_type(col_type):
                # Code-like columns (_code|_no|sku|serial) always upgrade
                should_upgrade = is_code_like
                # Business ID columns (*_id) upgrade only if UNIQUE and not FK
                if (
                    not should_upgrade
                    and col_name_lower.endswith("_id")
                    and is_unique
                    and not self._is_fk_column(table_schema, col_name)
                ):
                    should_upgrade = True
                if should_upgrade:
                    prefix = self._derive_code_template_prefix(col_name)
                    logger.warning(
                        "Stage3 Rule #24: fixing integer generator on TEXT code/id column to template",
                        column=col_name,
                        column_type=col_type,
                        template_prefix=prefix,
                    )
                    col["generator"] = "template"
                    col.pop("params", None)
                    col["params"] = {"template": f"{prefix}{{sequence:04d}}"}
                    return

        # Case 4: UNIQUE uuid on business identifier columns (*_id, *_no,
        # *_code) → upgrade to readable template.
        # Regression: employees.employee_id used generator: uuid, producing
        # unreadable UUIDs (550e8400-e29b-...) inconsistent with sibling
        # *_code/*_no columns (DEPT-/PROJ-/TASK-). Real HR/business systems
        # use sequential readable employee IDs (EMPL-0001).
        # Extended for *_no/*_code: orders.order_no used generator: uuid,
        # producing unreadable UUIDs inconsistent with sibling *_id columns.
        # Real business systems use sequential readable order numbers (ORDR-0001).
        # Skips columns explicitly named uuid/guid/token (designed for random).
        if is_unique and gen == "uuid" and self._is_business_identifier_column(col_name_lower):
            prefix = self._derive_code_template_prefix(col_name)
            logger.warning(
                "Stage3 Rule #24: upgrading UNIQUE uuid on business identifier column to template",
                column=col_name,
                template_prefix=prefix,
            )
            col["generator"] = "template"
            col.pop("params", None)
            col["params"] = {"template": f"{prefix}{{sequence:04d}}"}
            return

        # Case 5: UNIQUE code-like column with low-cardinality generator
        # (choice/weighted_choice) → upgrade to template. LLMs sometimes
        # confuse code columns with status columns (e.g., merchant_code gets
        # choice: [active, suspended, closed] instead of MERC-0001). A 3-value
        # choice generator cannot satisfy a UNIQUE constraint over 1000+ rows.
        # Code-like names (_code|_no|sku|serial) should always be sequential
        # templates, never enum-style choices.
        if is_unique and gen in ("choice", "weighted_choice") and is_code_like:
            prefix = self._derive_code_template_prefix(col_name)
            logger.warning(
                "Stage3 Rule #24: upgrading UNIQUE code column with low-cardinality choice generator to template",
                column=col_name,
                original_generator=gen,
                template_prefix=prefix,
                reason="choice cannot satisfy UNIQUE on code-like column (LLM confused code column with status column)",
            )
            col["generator"] = "template"
            col.pop("params", None)
            col["params"] = {"template": f"{prefix}{{sequence:04d}}"}
            return

        # Case 6: UNIQUE code-like column with date/timestamp/datetime generator
        # → upgrade to template. LLMs sometimes misclassify code columns as
        # date columns (e.g., project_code gets date generator producing
        # "2021-10-24" instead of "PROJ-0001"). Date values on a code-like
        # column are a semantic error even if they happen to be unique.
        if is_unique and gen in ("date", "timestamp", "datetime") and is_code_like:
            prefix = self._derive_code_template_prefix(col_name)
            logger.warning(
                "Stage3 Rule #24: upgrading UNIQUE code column with date-type generator to template",
                column=col_name,
                original_generator=gen,
                template_prefix=prefix,
                reason=(
                    "date/timestamp generator on code-like column produces "
                    "unreadable date values instead of business codes"
                ),
            )
            col["generator"] = "template"
            col.pop("params", None)
            col["params"] = {"template": f"{prefix}{{sequence:04d}}"}
            return

    @staticmethod
    def _is_business_identifier_column(col_name_lower: str) -> bool:
        """Check if column is a business identifier that should be sequential.

        Returns True for names ending in ``_id``, ``_no``, or ``_code``
        (e.g., ``employee_id``, ``order_no``, ``dept_code``) — these are
        readable business identifiers in HR/commerce systems.

        Returns False for columns explicitly designed to hold random UUIDs:
        ``uuid``, ``guid``, ``token``, ``*_uuid``, ``*_guid``, ``*_token``,
        ``session_uuid``. These should remain as ``uuid`` generator.
        """
        # Explicit random-UUID columns — keep uuid
        if col_name_lower in ("uuid", "guid", "token"):
            return False
        if col_name_lower.endswith("_uuid") or col_name_lower.endswith("_guid") or col_name_lower.endswith("_token"):
            return False
        # Business identifier columns (must end with _id/_no/_code, but not be
        # a UUID-named column). Includes bare "sku"/"serial" for completeness.
        if col_name_lower in ("sku", "serial"):
            return True
        return bool(
            col_name_lower.endswith("_id") or col_name_lower.endswith("_no") or col_name_lower.endswith("_code")
        )

    @staticmethod
    def _derive_code_template_prefix(col_name: str) -> str:
        """Derive a template prefix from a code/id column name.

        Strips common code/id suffixes (``_code``/``_no``/``_id``), takes the
        first 4 alphanumeric characters uppercased, and appends ``-``.

        Examples:
          - ``"project_code"`` → ``"PROJ-"``
          - ``"task_no"``       → ``"TASK-"``
          - ``"dept_code"``     → ``"DEPT-"``
          - ``"employee_id"``   → ``"EMPL-"``
          - ``"sku"``           → ``"SKU-"``
          - ``"serial"``        → ``"SERI-"``
        """
        base = re.sub(r"_(code|no|id)$", "", col_name.lower())
        prefix_chars = "".join(c for c in base[:5] if c.isalnum())[:4]
        return prefix_chars.upper() + "-"

    @staticmethod
    def _get_column_type_from_schema(table_schema: dict[str, Any], col_name: str) -> str | None:
        """Look up a column's type string from the schema dict.

        The schema dict is shaped by ``StagedSchemaAnalyzer._features_to_schema_dict``
        with ``columns`` as a list of ``ColumnInfo``-like dicts (each having
        ``name`` and ``type`` keys). Returns ``None`` if the column is not found.
        """
        columns = table_schema.get("columns")
        if not isinstance(columns, list):
            return None
        for col_info in columns:
            if not isinstance(col_info, dict):
                continue
            if col_info.get("name") == col_name:
                col_type = col_info.get("type")
                if isinstance(col_type, str):
                    return col_type
                return None
        return None

    @staticmethod
    def _is_text_type(col_type: str) -> bool:
        """Return True if the SQL type is a TEXT-family type.

        Recognised TEXT-family base types (case-insensitive, ignores params):
        TEXT, VARCHAR, NVARCHAR, CHAR, NCHAR, CLOB, NCLOB, STRING.
        """
        col_type_upper = col_type.upper()
        type_token = re.split(r"[(\s]", col_type_upper, maxsplit=1)[0]
        text_family = {"TEXT", "VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "CLOB", "NCLOB", "STRING"}
        return type_token in text_family

    @staticmethod
    def _is_integer_type(col_type: str) -> bool:
        """Return True if the SQL type is an INTEGER-family type.

        Recognised INTEGER-family base types (case-insensitive, ignores params):
        INTEGER, INT, BIGINT, SMALLINT, TINYINT, MEDIUMINT.

        Used by Rule #26 to decide whether ``random_float`` in a derive_from
        expression should be coerced to ``random_int`` (e.g., ``actual_hours
        INTEGER`` should not store fractional values like 25.57 hours).
        """
        col_type_upper = col_type.upper()
        type_token = re.split(r"[(\s]", col_type_upper, maxsplit=1)[0]
        integer_types = {"INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT", "MEDIUMINT"}
        return type_token in integer_types

    @staticmethod
    def _is_fk_column(table_schema: dict[str, Any], col_name: str) -> bool:
        """Return True if the column is a foreign key in the given table schema.

        Used by Rule #24 Case 3 to distinguish business ID columns (e.g.,
        ``employee_id`` TEXT UNIQUE, not a FK) from FK columns (e.g.,
        ``dept_id`` INTEGER, references departments.id). Without this check,
        Case 3 would incorrectly upgrade FK integer columns to template.
        """
        fks = table_schema.get("foreign_keys", [])
        if not isinstance(fks, list):
            return False
        for fk in fks:
            if not isinstance(fk, dict):
                continue
            cols = fk.get("columns", [])
            if isinstance(cols, list) and col_name in cols:
                return True
        return False

    def _apply_rule_19_check_constraint_bounds(self, table: dict[str, Any], table_schema: dict[str, Any]) -> None:
        """Rule #19: extract min_value/max_value from simple CHECK constraints.

        Parses simple CHECK constraints of the form ``col >= N`` or ``col <= N``
        and lifts (or lowers) the generator's ``min_value`` / ``max_value`` to
        satisfy the constraint. Only single-column, single-comparison CHECK
        expressions are parsed — complex expressions (AND/OR, BETWEEN, etc.)
        are skipped (the LLM's bounds are left in place and may produce some
        constraint violations, which is preferable to silently mis-parsing).

        Only applies to ``integer`` and ``float`` generators. Skips columns
        with ``derive_from`` (no generator params to adjust).
        """
        checks = table_schema.get("check_constraints", [])
        if not isinstance(checks, list):
            return

        # Build map of col_name -> {"min_value": N} or {"max_value": N}
        bounds: dict[str, dict[str, float]] = {}
        for check in checks:
            if not isinstance(check, dict):
                continue
            expr = check.get("expression")
            if not isinstance(expr, str):
                continue
            m = re.match(
                r"^\s*(\w+)\s*(>=|<=|>|<)\s*(-?[0-9]+(?:\.[0-9]+)?)\s*$",
                expr.strip(),
            )
            if not m:
                continue
            col_name, op, value_str = m.groups()
            value = float(value_str)
            # Track operator strictness so the bounds-application step can
            # adjust by ±1 for integer generators (strict ``>`` and ``<``
            # cannot be satisfied by the boundary value itself, which the
            # random generator may produce).
            if col_name not in bounds:
                bounds[col_name] = {}
            if op == ">=":
                bounds[col_name]["min_value"] = value
                bounds[col_name]["min_strict"] = False
            elif op == ">":
                bounds[col_name]["min_value"] = value
                bounds[col_name]["min_strict"] = True
            elif op == "<=":
                bounds[col_name]["max_value"] = value
                bounds[col_name]["max_strict"] = False
            elif op == "<":
                bounds[col_name]["max_value"] = value
                bounds[col_name]["max_strict"] = True

        for col in table.get("columns", []):
            if not isinstance(col, dict):
                continue
            col_name = col.get("name")
            if col_name not in bounds:
                continue
            # derive_from columns have no generator params to adjust
            if col.get("derive_from"):
                continue
            gen = col.get("generator")
            if gen not in ("integer", "float"):
                continue
            params = col.get("params")
            if not isinstance(params, dict):
                continue
            col_bounds = bounds[col_name]
            if "min_value" in col_bounds:
                check_min = col_bounds["min_value"]
                # For strict ``>`` on integer generators, the boundary value
                # itself is not a valid sample — bump by +1 so ``CHECK(x > 0)``
                # yields ``min_value=1`` rather than ``min_value=0`` (which
                # would generate 0 and violate the CHECK on batch insert).
                # Floats keep the bound as-is (no discrete step available).
                is_strict = col_bounds.get("min_strict", False)
                if is_strict and gen == "integer":
                    check_min = check_min + 1
                current_min = params.get("min_value", 0)
                if isinstance(current_min, (int, float)) and current_min < check_min:
                    logger.warning(
                        "Stage3 Rule #19: lifting min_value to satisfy CHECK constraint",
                        column=col_name,
                        original_min_value=current_min,
                        new_min_value=check_min,
                        strict_inequality=is_strict,
                    )
                    params["min_value"] = check_min if gen == "float" else int(check_min)
            if "max_value" in col_bounds:
                check_max = col_bounds["max_value"]
                # Symmetric to the min branch: strict ``<`` on integer
                # generators subtracts 1 so ``CHECK(x < 5)`` yields
                # ``max_value=4`` rather than ``max_value=5``.
                is_strict = col_bounds.get("max_strict", False)
                if is_strict and gen == "integer":
                    check_max = check_max - 1
                current_max = params.get("max_value", float("inf"))
                if isinstance(current_max, (int, float)) and current_max > check_max:
                    logger.warning(
                        "Stage3 Rule #19: lowering max_value to satisfy CHECK constraint",
                        column=col_name,
                        original_max_value=current_max,
                        new_max_value=check_max,
                        strict_inequality=is_strict,
                    )
                    params["max_value"] = check_max if gen == "float" else int(check_max)

    def _apply_rule_22_cross_column_date_range_isolation(
        self, table: dict[str, Any], table_schema: dict[str, Any]
    ) -> None:
        """Rule #22: isolate date ranges for cross-column date CHECK constraints.

        For CHECK constraints of the form ``<later_col> (>=|>) <earlier_col>`` or
        ``<earlier_col> (<=|<) <later_col>`` where both columns are DATE-family
        generators (``date``/``datetime``) with ``start_year``/``end_year`` params,
        ensures the ranges do not overlap:

          - If ``later_col.start_year > earlier_col.end_year``, no change.
          - Otherwise, splits the overall range at the midpoint and assigns:
              ``earlier_col.end_year = midpoint``
              ``later_col.start_year = midpoint + 1``

        This prevents batch-level CHECK constraint failures caused by random
        date generation producing ``end_date < start_date`` (sqlseed has no
        batch-level CHECK retry — failures are fatal).

        Skips:
          - Non-date-family generators (integer/float/string/etc.)
          - Columns with ``derive_from`` (no generator params to adjust)
          - Complex CHECK expressions (AND/OR, function calls, etc.)
        """
        checks = table_schema.get("check_constraints", [])
        if not isinstance(checks, list):
            return

        # Build column config map for quick lookup
        col_configs: dict[str, dict[str, Any]] = {}
        for col in table.get("columns", []):
            if isinstance(col, dict) and isinstance(col.get("name"), str):
                col_configs[col["name"]] = col

        for check in checks:
            if not isinstance(check, dict):
                continue
            expr = check.get("expression")
            if not isinstance(expr, str):
                continue
            parsed = self._parse_cross_column_date_comparison(expr)
            if parsed is None:
                continue
            later_col_name, earlier_col_name = parsed
            later_col = col_configs.get(later_col_name)
            earlier_col = col_configs.get(earlier_col_name)
            if not isinstance(later_col, dict) or not isinstance(earlier_col, dict):
                continue
            # If either column was stripped by Rule #17 (DATE-family source column
            # whose derive_from was removed), supplement a date generator so the
            # range-isolation logic below can adjust its year params. This handles
            # the Rule #17 + Rule #22 interaction: Rule #17 strips unsafe
            # derive_from (would crash on float(date)), leaving the column empty;
            # Rule #22 then needs to give it a date generator and isolate the range.
            self._ensure_date_generator_for_date_column(later_col, table_schema)
            self._ensure_date_generator_for_date_column(earlier_col, table_schema)
            # Both must be date-family generators with start_year/end_year params
            if not self._has_date_year_range(later_col) or not self._has_date_year_range(earlier_col):
                continue
            # Skip columns with derive_from (no generator params to adjust)
            if later_col.get("derive_from") or earlier_col.get("derive_from"):
                continue
            later_params = later_col["params"]
            earlier_params = earlier_col["params"]
            later_start = int(later_params["start_year"])
            later_end = int(later_params["end_year"])
            earlier_start = int(earlier_params["start_year"])
            earlier_end = int(earlier_params["end_year"])
            # Sanity check: if a previous (buggy) Rule #22 run left either
            # column with an invalid range (start_year > end_year), reset
            # both columns to the default 2000-2024 range before isolation.
            # Without this, the date generator would always return start_year
            # (since end_year < start_year), causing batch CHECK failures.
            if earlier_start > earlier_end:
                logger.warning(
                    "Stage3 Rule #22: resetting invalid earlier_col year range",
                    column=earlier_col_name,
                    invalid_start_year=earlier_start,
                    invalid_end_year=earlier_end,
                )
                earlier_params["start_year"] = 2000
                earlier_params["end_year"] = 2024
                earlier_start = 2000
                earlier_end = 2024
            if later_start > later_end:
                logger.warning(
                    "Stage3 Rule #22: resetting invalid later_col year range",
                    column=later_col_name,
                    invalid_start_year=later_start,
                    invalid_end_year=later_end,
                )
                later_params["start_year"] = 2000
                later_params["end_year"] = 2024
                later_start = 2000
                later_end = 2024
            # Already isolated? (later is entirely after earlier)
            if later_start > earlier_end:
                continue
            # Compute the OVERLAP (intersection) range — this is where both
            # columns can generate dates and isolation is needed. Using the
            # union range (min/max) would produce a midpoint outside one
            # column's individual range, leaving that column with an invalid
            # ``end_year < start_year`` (or ``start_year > end_year``) state.
            overlap_start = max(later_start, earlier_start)
            overlap_end = min(later_end, earlier_end)
            # No overlap (e.g., later is entirely before earlier)? Skip —
            # the CHECK is structurally violated and Rule #22 cannot fix it
            # by range isolation alone.
            if overlap_end < overlap_start:
                continue
            # Split the overlap at midpoint. Because midpoint is in
            # [overlap_start, overlap_end] ⊆ [earlier_start, earlier_end] and
            # ⊆ [later_start, later_end], both new bounds remain valid.
            midpoint = (overlap_start + overlap_end) // 2
            new_earlier_end = midpoint
            new_later_start = midpoint + 1
            # Degenerate single-year overlap: midpoint == overlap_end, so
            # new_later_start == overlap_end + 1. If overlap_end == later_end,
            # new_later_start > later_end — bail out (cannot isolate safely).
            if new_later_start > later_end or new_earlier_end < earlier_start:
                continue
            logger.warning(
                "Stage3 Rule #22: isolating date ranges for cross-column CHECK",
                check_expression=expr.strip(),
                earlier_column=earlier_col_name,
                later_column=later_col_name,
                earlier_old_end_year=earlier_end,
                earlier_new_end_year=new_earlier_end,
                later_old_start_year=later_start,
                later_new_start_year=new_later_start,
            )
            earlier_params["end_year"] = new_earlier_end
            later_params["start_year"] = new_later_start

    @staticmethod
    def _parse_cross_column_date_comparison(expr: str) -> tuple[str, str] | None:
        """Parse a cross-column date comparison CHECK expression.

        Recognised patterns (case-insensitive operator, whitespace-tolerant):

          - ``<later_col> (>=|>) <earlier_col>`` → ``(later_col, earlier_col)``
          - ``<earlier_col> (<=|<) <later_col>`` → ``(later_col, earlier_col)``

        Returns:
            ``(later_col_name, earlier_col_name)`` if the expression matches a
            recognised pattern, else ``None``. Both column names must be
            word characters (letters/digits/underscore) — numeric literals or
            complex expressions are rejected.
        """
        expr_stripped = expr.strip()
        # Pattern: later_col >= earlier_col  (or >)
        m = re.match(r"^\s*(\w+)\s*(>=|>)\s*(\w+)\s*$", expr_stripped)
        if m:
            later_col, _op, earlier_col = m.groups()
            # Reject if either side looks like a number
            if later_col.isdigit() or earlier_col.isdigit():
                return None
            return (later_col, earlier_col)
        # Pattern: earlier_col <= later_col  (or <)
        m = re.match(r"^\s*(\w+)\s*(<=|<)\s*(\w+)\s*$", expr_stripped)
        if m:
            earlier_col, _op, later_col = m.groups()
            if earlier_col.isdigit() or later_col.isdigit():
                return None
            return (later_col, earlier_col)
        return None

    @staticmethod
    def _has_date_year_range(col: dict[str, Any]) -> bool:
        """Check whether the column has a date-family generator with year-range params."""
        if col.get("generator") not in ("date", "datetime"):
            return False
        params = col.get("params")
        if not isinstance(params, dict):
            return False
        start = params.get("start_year")
        end = params.get("end_year")
        return isinstance(start, int) and isinstance(end, int)

    def _ensure_date_generator_for_date_column(self, col: dict[str, Any], table_schema: dict[str, Any]) -> None:
        """Supplement or convert a date-family generator for cross-column CHECK.

        Three cases:

        1. **Stripped column (no generator)**: When Rule #17 strips a DATE-family
           source column's ``derive_from`` + ``expression`` (because
           ``float(date)`` would crash), the column is left with only its
           ``name``. Rule #22 still needs to enforce the cross-column date
           CHECK, so this helper gives the column a ``date``/``datetime``
           generator with a default year range (2000-2024).

        2. **timestamp generator on TIMESTAMP-type column**: The ``timestamp``
           generator has no ``start_year``/``end_year`` params, so Rule #22
           cannot isolate year ranges. This helper converts it to ``datetime``
           (with default year range 2000-2024) so the cross-column CHECK
           (e.g., ``end_time >= start_time`` on TIMESTAMP columns) is enforced.
           Without this conversion, batch-level CHECK failures would occur
           because random timestamps could violate ``end_time >= start_time``.

        3. **date/datetime generator without year-range params**: LLM may return
           ``date`` with empty params ``{}`` (no start_year/end_year). Rule #22
           cannot isolate ranges without year params. This helper supplements
           the default year range (2000-2024) so range isolation can proceed.

        Only acts when:
          - Case 1: The column has NO ``generator`` key (or it is None), AND
            the column exists in ``table_schema`` with a DATE-family type.
          - Case 2: The column has ``generator == "timestamp"`` AND the column
            exists in ``table_schema`` with a TIMESTAMP/DATETIME-family type.
          - Case 3: The column has ``generator`` in ("date", "datetime") but
            params is missing start_year or end_year.

        The default range 2000-2024 is chosen so the subsequent range-isolation
        logic in Rule #22 has room to split at the midpoint.
        """
        gen = col.get("generator")
        col_name = col.get("name")
        if not isinstance(col_name, str):
            return
        columns = table_schema.get("columns")
        if not isinstance(columns, list):
            return

        # Case 1: stripped column (no generator) → supplement date/datetime generator
        if gen is None:
            for col_info in columns:
                if not isinstance(col_info, dict) or col_info.get("name") != col_name:
                    continue
                col_type = col_info.get("type")
                if not isinstance(col_type, str):
                    break
                col_type_upper = col_type.upper()
                type_token = re.split(r"[(\s]", col_type_upper, maxsplit=1)[0]
                date_family = {"DATE", "DATETIME", "TIMESTAMP", "TIME", "SMALLDATETIME", "DATETIME2"}
                if type_token not in date_family:
                    break
                # Use "date" for plain DATE, "datetime" for the rest
                gen_name = "date" if type_token == "DATE" else "datetime"
                col["generator"] = gen_name
                col["params"] = {"start_year": 2000, "end_year": 2024}
                logger.warning(
                    "Stage3 Rule #22: supplementing date generator for stripped column",
                    column=col_name,
                    column_type=type_token,
                    generator=gen_name,
                )
                break
            return

        # Case 2: timestamp generator on TIMESTAMP-type column → convert to datetime
        # so Rule #22 can apply year-range isolation. Without this conversion,
        # cross-column CHECK (end_time >= start_time) on TIMESTAMP columns
        # would be silently skipped, causing batch-level CHECK failures.
        if gen == "timestamp":
            for col_info in columns:
                if not isinstance(col_info, dict) or col_info.get("name") != col_name:
                    continue
                col_type = col_info.get("type")
                if not isinstance(col_type, str):
                    break
                col_type_upper = col_type.upper()
                type_token = re.split(r"[(\s]", col_type_upper, maxsplit=1)[0]
                timestamp_family = {"TIMESTAMP", "DATETIME", "SMALLDATETIME", "DATETIME2"}
                if type_token not in timestamp_family:
                    break
                logger.warning(
                    "Stage3 Rule #22: converting timestamp generator to datetime for cross-column CHECK",
                    column=col_name,
                    column_type=type_token,
                )
                col["generator"] = "datetime"
                col["params"] = {"start_year": 2000, "end_year": 2024}
                break
            return

        # Case 3: date/datetime generator without year-range params → supplement defaults.
        # LLM may return `generator: date` with empty params `{}`, which lacks
        # start_year/end_year. Without year params, Rule #22 cannot isolate ranges,
        # causing cross-column CHECK failures (e.g., end_date >= start_date).
        if gen in ("date", "datetime"):
            params = col.get("params")
            if not isinstance(params, dict):
                params = {}
                col["params"] = params
            if "start_year" not in params or "end_year" not in params:
                logger.warning(
                    "Stage3 Rule #22: supplementing missing year-range params for date generator",
                    column=col_name,
                    generator=gen,
                )
                params.setdefault("start_year", 2000)
                params.setdefault("end_year", 2024)


def _bound_unbounded_quantifier(match: re.Match[str]) -> str:
    """Replace {N,} with {N,N+5} (module-level helper to satisfy B023)."""
    n = int(match.group(1))
    return f"{{{n},{n + 5}}}"
