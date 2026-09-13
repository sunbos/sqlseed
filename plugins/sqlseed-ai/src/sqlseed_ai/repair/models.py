"""Layer 3: Repair data structures.

Spec reference: Section 5.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlseed_ai.validator.models import ViolationReport


@dataclass
class AppliedFix:
    """Record of a single repair (for Diff learning)."""

    table: str
    columns: list[str]
    fix_strategy: str
    before: dict[str, Any]
    after: dict[str, Any]
    violation_kind: str
    success: bool = True


@dataclass
class RepairResult:
    """Aggregated repair outcome."""

    config: dict[str, Any]
    applied_fixes: list[AppliedFix]
    unfixable: list[ViolationReport]
    fix_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.fix_count = len(self.applied_fixes)
