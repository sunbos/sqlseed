"""Layer 1: Sparse contract matrix + resolver.

Spec reference: Section 3.2.

Defines :class:`ContractViolation` (a single bad generator/type/constraints
combination) and :class:`ContractResolver` (merged query over builtin +
learned violations with specificity-priority matching).

The matrix is a *closed set* — only known-bad combinations are listed.
Unlisted combinations default to COMPATIBLE (no violation). Gaps are
caught by Layer 5 property-based tests in CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


class ViolationKind(Enum):
    """Kind of contract violation."""

    CRASH = "crash"
    SEMANTIC_ERROR = "semantic_error"
    UNIQUE_UNSATISFIABLE = "unique_unsatisfiable"
    CONDITIONAL = "conditional"


@dataclass
class ContractViolation:
    """Single contract violation definition.

    Identity (used for ``__hash__``/``__eq__`` and set dedup) covers only
    the core fields: ``generator``, ``column_type``, ``constraints``,
    ``kind``, ``fix_strategy``. The ``predicate``, ``learned_at``,
    ``source``, and ``schema_hash`` fields are metadata and do not affect
    identity — this allows a learned violation to override a builtin one
    with the same identity without producing duplicate set entries.
    """

    generator: str
    column_type: str  # "ANY" for wildcard
    constraints: frozenset[str]  # empty set for wildcard
    kind: ViolationKind
    fix_strategy: str  # whitelist function name
    fix_params: dict[str, Any] = field(default_factory=dict)
    predicate: Callable[[dict[str, Any]], bool] | None = None
    source: str = "builtin"  # "builtin" | "auto_learned"
    learned_at: datetime | None = None
    schema_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializable form (predicate excluded; datetime as ISO string)."""
        return {
            "generator": self.generator,
            "column_type": self.column_type,
            "constraints": list(self.constraints),
            "kind": self.kind.value,
            "fix_strategy": self.fix_strategy,
            "fix_params": self.fix_params,
            "source": self.source,
            "learned_at": self.learned_at.isoformat() if self.learned_at else None,
            "schema_hash": self.schema_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContractViolation:
        """Deserialize (predicate set to None for learned contracts)."""
        return cls(
            generator=data["generator"],
            column_type=data["column_type"],
            constraints=frozenset(data.get("constraints", [])),
            kind=ViolationKind(data["kind"]),
            fix_strategy=data["fix_strategy"],
            fix_params=data.get("fix_params", {}),
            predicate=None,  # Learned contracts are declarative
            source=data.get("source", "auto_learned"),
            learned_at=datetime.fromisoformat(data["learned_at"]) if data.get("learned_at") else None,
            schema_hash=data.get("schema_hash"),
        )

    def __hash__(self) -> int:
        """Identity by core fields only (excludes predicate/learned_at/source)."""
        return hash((self.generator, self.column_type, self.constraints, self.kind, self.fix_strategy))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ContractViolation):
            return NotImplemented
        return (
            self.generator == other.generator
            and self.column_type == other.column_type
            and self.constraints == other.constraints
            and self.kind == other.kind
            and self.fix_strategy == other.fix_strategy
        )


class ContractResolver:
    """Merged query: builtin + learned violations.

    Adversarial fix (C2 from cross-agent review): the lookup is O(N) where
    N is the matrix size (~100 entries, <1ms in practice), NOT O(1). True
    O(1) would require a ``dict[(generator, column_type, frozenset[str]),
    list[ContractViolation]]`` index. The current linear scan is fast
    enough at this scale; if matrix grows beyond ~500 entries, consider
    adding the dict index.

    Priority on ties (same specificity):
        1. ``learned`` violations override ``builtin`` (allows LLM/user to
           correct unreasonable defaults).
        2. Lower specificity number wins (1=exact > 2=partial wildcard >
           3=full wildcard).
    """

    def __init__(self, builtin: set[ContractViolation], learned: set[ContractViolation]) -> None:
        self._builtin = builtin
        self._learned = learned

    def check(
        self,
        generator: str,
        column_type: str,
        constraints: frozenset[str],
        config: dict[str, Any],
    ) -> ContractViolation | None:
        """Check if combination is violated, return definition or None (compatible).

        Args:
            generator: Generator name (e.g., "integer", "choice").
            column_type: Column type normalized to uppercase (e.g., "TIMESTAMP").
            constraints: Frozenset of constraint tags (e.g., frozenset({"UNIQUE"})).
            config: Optional context dict for predicate evaluation
                (e.g., {"row_count": 100, "pool_size": 10}).

        Returns:
            The matching :class:`ContractViolation` with highest priority,
            or ``None`` if the combination is compatible.
        """
        matches: list[tuple[str, int, ContractViolation]] = []
        for source, violations in (("learned", self._learned), ("builtin", self._builtin)):
            for v in violations:
                if v.generator != generator:
                    continue
                specificity = self._match_specificity(v, column_type, constraints)
                if specificity is None:
                    continue
                # Conditional violations need predicate evaluation
                if v.predicate is not None and not v.predicate(config):
                    continue
                matches.append((source, specificity, v))
        if not matches:
            return None
        # Priority: specificity (1=exact, 2=partial wildcard, 3=full wildcard)
        # Then: learned > builtin (allows LLM/user to override unreasonable defaults)
        matches.sort(key=lambda x: (x[1], 0 if x[0] == "learned" else 1))
        return matches[0][2]

    @staticmethod
    def _match_specificity(v: ContractViolation, col_type: str, constraints: frozenset[str]) -> int | None:
        """Return specificity level (1=exact, 2=partial, 3=full wildcard) or None (no match)."""
        type_match = v.column_type == col_type
        type_wildcard = v.column_type == "ANY"
        cons_match = v.constraints == constraints
        cons_subset = v.constraints.issubset(constraints) and bool(v.constraints)
        cons_wildcard = not v.constraints

        if type_match and cons_match:
            return 1
        if type_match and (cons_subset or cons_wildcard):
            return 2
        if type_wildcard and (cons_match or cons_subset or cons_wildcard):
            return 3
        return None
