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
    def analyze(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Analyze database via staged pipeline. Implemented in Task 7+."""
        raise NotImplementedError("StagedSchemaAnalyzer.analyze() implemented in Task 7+")
