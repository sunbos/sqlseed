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

# Single source of truth for Defense 1 + Defense 7 whitelists lives in
# contracts/registry.py. Previously diff_learner.py maintained its own
# copies which drifted out of sync with registry.py — the two lists
# shared only 2 of 19 strategy names and 6 of 20 forbidden keys, leaving
# gaps that allowed RCE payloads (e.g. {"expression": "eval('...')"})
# to slip past DiffLearner's check only to be caught later by registry.
from sqlseed_ai.contracts.registry import FORBIDDEN_PERSIST_KEYS, SAFE_FIX_STRATEGIES

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.repair.models import AppliedFix

logger = get_logger(__name__)


# Dangerous substrings to scan recursively in string values of the
# ``after`` dict. Catches payloads like ``"eval('1+1')"`` even when the
# top-level key is benign (e.g. ``{"params": {"note": "eval('...')"}}``).
_DANGEROUS_SUBSTRINGS: tuple[str, ...] = (
    "__import__",
    "subprocess",
    "os.system",
    "os.popen",
    "eval(",
    "exec(",
    "compile(",
    "globals()",
    "locals()",
    "getattr(",
    "setattr(",
    "delattr(",
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
        kind = ViolationKind(fix.violation_kind) if fix.violation_kind in valid_values else ViolationKind.SEMANTIC_ERROR
        return ContractViolation(
            generator=generator,
            column_type=column_type,
            constraints=constraints,
            kind=kind,
            fix_strategy=fix.fix_strategy,
            fix_params={k: v for k, v in fix.after.items() if isinstance(v, (str, int, float, bool, list, tuple))},
            predicate=None,
            source="auto_learned",
            learned_at=datetime.now(timezone.utc),
            schema_hash=self._schema_hash,
        )

    @staticmethod
    def _contains_forbidden_keys(after: dict[str, Any]) -> bool:
        """Recursively check the after-dict for forbidden keys and dangerous substrings.

        Scans the full nested structure (dicts, lists, strings) so LLM
        payloads hidden inside ``{"params": {"expression": "eval('...')"}}``
        cannot slip past. Previously this only scanned top-level keys and
        a 4-item substring allowlist on top-level string values, leaving
        ``expression`` (the actual RCE entry point) and nested dicts
        completely unchecked at this layer.
        """

        def _scan(obj: Any) -> bool:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in FORBIDDEN_PERSIST_KEYS:
                        return True
                    if _scan(v):
                        return True
            elif isinstance(obj, list):
                for item in obj:
                    if _scan(item):
                        return True
            elif isinstance(obj, str):
                lowered = obj.lower()
                if any(s in lowered for s in _DANGEROUS_SUBSTRINGS):
                    return True
            return False

        return _scan(after)
