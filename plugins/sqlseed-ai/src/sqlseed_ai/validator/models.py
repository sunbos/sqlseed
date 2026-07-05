"""Layer 2: Data structures for validation results.

Spec reference: Section 4.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class ConstraintType(Enum):
    """Type of database constraint that was violated."""

    FK = "fk"
    CHECK = "check"
    UNIQUE = "unique"
    NOT_NULL = "not_null"


@dataclass
class ViolationReport:
    """Normalized violation report (dialect-agnostic).

    Adversarial fix (C3 from cross-agent review): added ``message`` field.
    The LLMHealer.build_prompt() in Task 3.4 reads ``v.message`` to inject
    the raw DB error text into the healer prompt. Without this field the
    Plan's Task 3.4 test code would raise TypeError at runtime.
    """

    table: str
    columns: list[str]
    constraint_type: ConstraintType
    severity: Literal["crash", "semantic_error", "unique_unsatisfiable"]
    raw_expression: str | None = None
    constraint_name: str | None = None
    is_composite: bool = False
    fix_hint: str | None = None
    fix_params: dict[str, Any] = field(default_factory=dict)
    source: str = "validation"
    message: str | None = None  # human-readable error text (used by LLMHealer)


@dataclass
class ColumnGroup:
    """Composite FK coordinated generation group (Defense 5).

    When a composite FK is detected, all member columns are bound into a
    single :class:`ColumnGroup`. If any member fails, ALL members degrade
    together to a coordinated fallback (e.g., joint SELECT from parent).
    """

    group_id: str
    columns: list[str]
    parent_table: str
    parent_columns: list[str]
    degrade_together: bool = True


@dataclass
class ValidationResult:
    """Aggregated validation outcome for a single table config."""

    violations: list[ViolationReport]
    column_groups: list[ColumnGroup]
    is_clean: bool = field(init=False)

    def __post_init__(self) -> None:
        self.is_clean = len(self.violations) == 0
