"""Layer 4: Healer data structures.

Spec reference: Section 6.2 + 4-Level Heal Architecture (2026-07-08).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sqlseed_ai.contracts.matrix import ContractViolation
    from sqlseed_ai.repair.models import AppliedFix


class DegradeReason(Enum):
    """Reasons why a column was degraded to the Core 9-level mapper."""

    LLM_TIMEOUT = "llm_timeout"
    LLM_OSCILLATION = "llm_oscillation"
    LLM_FAILURE = "llm_failure"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"
    CASCADE = "cascade"  # set by ProgressiveDegrader for downstream columns


class FailureType(Enum):
    """Classification of LLM failures for routing decisions."""

    CONTEXT_OVERFLOW = "context_overflow"  # Context window exceeded
    EMPTY_RESPONSE = "empty_response"  # LLM returned empty string
    JSON_FORMAT = "json_format"  # JSON parsing failed
    SEMANTIC = "semantic"  # Validator rejected config
    NETWORK = "network"  # API timeout/connection/rate limit
    UNKNOWN = "unknown"  # Unclassified (treated as SEMANTIC)


@dataclass
class SubgraphTask:
    """A healing subgraph: tables to be healed together (SCC or single-table)."""

    task_id: str
    tables: list[str]
    is_scc: bool = False
    parent_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealAttempt:
    """Record of a single LLM healer attempt.

    Spec reference: Section 4.3 — tracks which level was tried, the
    failure type (if any), latency, token estimate, and error message.
    """

    level: int  # 1, 2, or 3 (which healer was tried)
    failure_type: FailureType | None = None  # None if success
    latency_ms: int = 0  # elapsed time in milliseconds
    token_estimate: int = 0  # prompt token estimate
    error_message: str | None = None
    applied_fixes: list[AppliedFix] = field(default_factory=list)


@dataclass
class FKInfo:
    """Foreign key reference info for Level 2 column context."""

    ref_table: str
    ref_column: str


@dataclass
class ColumnContext:
    """Minimal dependency info for Level 2 column-level healing."""

    table_name: str
    column_name: str
    column_type: str
    nullable: bool
    default: Any
    is_unique: bool
    check_constraints: list[dict[str, Any]]  # all CHECKs this column participates in
    derive_from_sources: list[tuple[str, str]]  # (column_name, column_type) pairs
    derive_from_downstream: list[str]  # downstream column names
    cross_column_refs: list[tuple[str, str]]  # (column_name, column_type) pairs
    fk_info: FKInfo | None


@dataclass
class Level1Result:
    """Result of Level1SubgraphHealer.heal()."""

    success: bool
    config_patch: dict[str, Any] | None
    raw_response: str | None = None
    error: Exception | None = None
    elapsed_seconds: float = 0.0
    prompt_tokens: int = 0


@dataclass
class Level2Result:
    """Result of Level2ColumnHealer.heal_column() for a single column."""

    success: bool
    column: str
    config_patch: dict[str, Any] | None = None
    raw_response: str | None = None
    error: Exception | None = None
    elapsed_seconds: float = 0.0
    prompt_tokens: int = 0


@dataclass
class Level3Result:
    """Result of Level3CompactHealer.heal_compact()."""

    success: bool
    mode: Literal["compact", "ultra_compact"]
    config_patch: dict[str, Any] | None = None
    raw_response: str | None = None
    error: Exception | None = None
    elapsed_seconds: float = 0.0
    prompt_tokens: int = 0
    json_repaired: bool = False


@dataclass
class HealResult:
    """Final result of HealOrchestrator.heal().

    Extended from the original 2-level HealResult to carry 4-level
    diagnostics (level_used, failure_type, attempts) while preserving
    ``config`` and ``degraded_columns`` for AutoHealOrchestrator consumers.
    """

    config: dict[str, Any]
    success: bool = False
    level_used: int = 0  # 1, 2, 3, or 4
    failure_type: FailureType | None = None  # set when success=False
    degraded_columns: list[str] = field(default_factory=list)
    degrade_reasons: dict[str, DegradeReason] = field(default_factory=dict)
    applied_fixes: list[AppliedFix] = field(default_factory=list)
    learned_contracts: list[ContractViolation] = field(default_factory=list)
    attempts: list[HealAttempt] = field(default_factory=list)
    total_attempts: int = 0
    total_elapsed: float = 0.0
