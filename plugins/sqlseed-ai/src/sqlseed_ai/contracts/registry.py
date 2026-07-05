"""Layer 1: Local JSON-persisted learned contracts registry.

Defenses 1 (safety sandbox) + 7 (RCE interception).
Spec reference: Section 3.4.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlseed_ai.contracts.matrix import ContractViolation

from sqlseed._utils.logger import get_logger
from sqlseed._utils.paths import get_cache_dir

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)


# [Defense 1] Whitelist of safe fix strategies that may be persisted.
# Anything outside this set is refused at registry add() time.
SAFE_FIX_STRATEGIES = frozenset({
    "switch_generator", "upgrade_to_template", "expand_pool",
    "adjust_bounds", "add_unique_suffix", "normalize_params",
    "break_derive_from_cycle", "align_fk_max_value",
    "isolate_date_ranges", "semantic_upgrade", "fix_self_reference",
    "coerce_float_to_int", "align_group_generators",
})

# [Defense 7] RCE defense: forbid persistence of params whose values
# could carry arbitrary code (e.g., expression strings, lambda source,
# eval/exec payloads). These keys are stripped or refused before write.
FORBIDDEN_PERSIST_KEYS = frozenset({
    "custom_function", "expression", "code", "eval", "exec", "lambda",
})


class LearnedContractsRegistry:
    """Local JSON-persisted learned contracts registry.

    The registry is a safety-sandboxed JSON file (Defense 1) that stores
    learned :class:`ContractViolation` entries across runs. Persistence
    is gated by two checks:

    1. ``fix_strategy`` must be in :data:`SAFE_FIX_STRATEGIES` (whitelist).
    2. ``fix_params`` must not contain any key in
       :data:`FORBIDDEN_PERSIST_KEYS` (RCE defense, Defense 7).

    Corruption-tolerant: if the JSON file is malformed, the registry
    starts empty rather than crashing (Layer 1 must never block startup).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_cache_dir() / "learned_contracts.json")
        self._contracts: set[ContractViolation] = set()
        self._load()

    def add(self, violation: ContractViolation) -> bool:
        """Add a violation to the registry and persist.

        Returns:
            True if accepted; False if refused by safety sandbox.
        """
        # [Defense 7] Refuse to persist dangerous params
        if any(k in violation.fix_params for k in FORBIDDEN_PERSIST_KEYS):
            logger.warning(
                "Refusing to persist unsafe contract (forbidden param keys)",
                strategy=violation.fix_strategy,
            )
            return False
        # [Defense 1] Must be whitelist strategy
        if violation.fix_strategy not in SAFE_FIX_STRATEGIES:
            logger.warning(
                "Refusing to persist non-whitelist strategy",
                strategy=violation.fix_strategy,
            )
            return False
        self._contracts.add(violation)
        self._save()
        return True

    def filter_by_schema_hash(self, current_hash: str) -> set[ContractViolation]:
        """Return only contracts matching the given schema_hash."""
        return {v for v in self._contracts if v.schema_hash == current_hash}

    def size(self) -> int:
        """Number of learned contracts currently in the registry."""
        return len(self._contracts)

    def _load(self) -> None:
        """Load from disk; corrupt files are treated as empty."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for item in data.get("contracts", []):
                self._contracts.add(ContractViolation.from_dict(item))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning(
                "Learned contracts registry corrupted, ignoring",
                error=str(e),
                path=str(self._path),
            )

    def _save(self) -> None:
        """Persist current contracts to disk as JSON."""
        data = {
            "schema_hash": None,
            "contracts": [v.to_dict() for v in self._contracts],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
