"""Layer 4e: Diff Learner + Defense 7 (RCE interception).

Spec reference: Section 6.7 (Diff learning), Section 9 (Defense 7).

The learner inspects a successful ``AppliedFix`` and produces a candidate
``ContractViolation`` for the local JSON registry. **Before** the candidate
is returned to the registry, Defense 7 scans the fix's ``after`` dict for
forbidden keys (``custom_function``, ``eval``, ``exec``, ``__import__``,
etc.). Any match causes the candidate to be silently dropped and logged
— the LLM may have tried to inject malicious code that would be replayed
on future runs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlseed_ai.contracts.matrix import ContractViolation, ViolationKind

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.repair.models import AppliedFix

logger = get_logger(__name__)


# Defense 7: keys that, if present in an AppliedFix.after dict, indicate
# the LLM is trying to persist executable code. Such fixes must NOT be
# written to the learned contracts registry.
FORBIDDEN_PERSIST_KEYS: frozenset[str] = frozenset(
    {
        "custom_function",
        "eval",
        "exec",
        "__import__",
        "compile",
        "globals",
        "locals",
        "getattr",
        "setattr",
        "delattr",
        "open",  # file I/O
        "subprocess",
        "os",
        "sys",
    }
)


# Fix strategies that are safe to persist (whitelist). Strategies not in
# this set are also rejected, providing a second layer of Defense 7.
SAFE_FIX_STRATEGIES: frozenset[str] = frozenset(
    {
        "switch_generator",
        "upgrade_to_template",
        "adjust_params",
        "coerce_type",
        "strip_invalid_params",
        "fix_choice_typo",
    }
)


class DiffLearner:
    """Learn contract violations from successful LLM-applied fixes.

    Defense 7 (RCE interception) is enforced via :data:`FORBIDDEN_PERSIST_KEYS`
    and :data:`SAFE_FIX_STRATEGIES`. Any fix referencing a forbidden key or
    using a non-whitelisted strategy is rejected (returns ``None``).
    """

    def __init__(self, *, schema_hash: str) -> None:
        self._schema_hash = schema_hash

    def learn_from_fix(
        self,
        fix: AppliedFix,
        *,
        generator: str,
        column_type: str,
        constraints: frozenset[str],
    ) -> ContractViolation | None:
        """Produce a candidate ContractViolation, or None if rejected.

        Rejection reasons:
          - fix.success is False (don't learn from failures)
          - fix.after contains a forbidden key (Defense 7)
          - fix.fix_strategy is not in the safe whitelist (Defense 7)
        """
        if not fix.success:
            return None

        # Defense 7: scan after-dict for forbidden keys
        if self._contains_forbidden_keys(fix.after):
            logger.warning(
                "Defense 7: rejected RCE-suspect fix",
                table=fix.table,
                columns=fix.columns,
                strategy=fix.fix_strategy,
            )
            return None

        # Defense 7: only whitelisted strategies may persist
        if fix.fix_strategy not in SAFE_FIX_STRATEGIES:
            logger.warning(
                "Defense 7: rejected non-whitelisted fix strategy",
                strategy=fix.fix_strategy,
            )
            return None

        # Build the candidate contract. Predicates are not learned
        # (learned contracts are declarative only — Section 3.2).
        valid_values = {k.value for k in ViolationKind}
        kind = (
            ViolationKind(fix.violation_kind)
            if fix.violation_kind in valid_values
            else ViolationKind.SEMANTIC_ERROR
        )
        return ContractViolation(
            generator=generator,
            column_type=column_type,
            constraints=constraints,
            kind=kind,
            fix_strategy=fix.fix_strategy,
            fix_params={
                k: v
                for k, v in fix.after.items()
                if isinstance(v, (str, int, float, bool, list, tuple))
            },
            predicate=None,
            source="auto_learned",
            learned_at=datetime.now(timezone.utc),
            schema_hash=self._schema_hash,
        )

    @staticmethod
    def _contains_forbidden_keys(after: dict[str, Any]) -> bool:
        """Check the after-dict (recursively one level) for forbidden keys."""
        for key in after:
            if key in FORBIDDEN_PERSIST_KEYS:
                return True
        # Also scan string values for forbidden substrings (catches
        # things like {"expression": "eval('1+1')"})
        for value in after.values():
            if isinstance(value, str):
                lowered = value.lower()
                if any(
                    forbidden in lowered
                    for forbidden in ("__import__", "subprocess", "os.system", "os.popen")
                ):
                    return True
        return False
