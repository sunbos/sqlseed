"""Layer 4: Healer data structures.

Spec reference: Section 6.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

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


@dataclass
class SubgraphTask:
    """A healing subgraph: tables to be healed together (SCC or single-table)."""

    task_id: str
    tables: list[str]
    is_scc: bool = False
    parent_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealAttempt:
    """Record of a single LLM healer attempt."""

    attempt_num: int
    prompt_tokens: int
    elapsed_seconds: float
    success: bool
    error: str | None = None
    applied_fixes: list[AppliedFix] = field(default_factory=list)


@dataclass
class HealResult:
    """Final result of healing a subgraph."""

    config: dict[str, Any]
    applied_fixes: list[AppliedFix]
    degraded_columns: list[str]
    degrade_reasons: dict[str, DegradeReason]
    learned_contracts: list[ContractViolation] = field(default_factory=list)
    total_attempts: int = 0
    total_elapsed: float = 0.0
