"""Layer 1: Local JSON-persisted learned contracts registry.

Defenses 1 (safety sandbox) + 7 (RCE interception) + 8 (schema_hash versioning).
Spec reference: Section 3.4, 8, 11.

The registry persists successful ``DiffLearner`` candidates to a local JSON
file. Defense 1 enforces atomic save (temp file + rename). Defense 8 stamps
each entry with ``schema_hash`` so stale entries are filtered out.

Defense 7 (RCE interception) is re-checked at load time: any entry whose
``fix_strategy`` is not in the safe whitelist, or whose ``fix_params``
contain forbidden keys, is silently dropped. This catches the case where
the JSON file was tampered with out-of-band.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from typing import TYPE_CHECKING, Any

from sqlseed_ai.contracts.matrix import ContractViolation

from sqlseed._utils.logger import get_logger
from sqlseed._utils.paths import get_cache_dir

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)


# [Defense 1] Whitelist of safe fix strategies that may be persisted.
# Anything outside this set is refused at registry add() time.
# This is the SINGLE source of truth — diff_learner.py imports from here.
SAFE_FIX_STRATEGIES = frozenset(
    {
        # From RepairExecutor (local rule-based fixes):
        "switch_generator",
        "upgrade_to_template",
        "expand_pool",
        "adjust_bounds",
        "add_unique_suffix",
        "normalize_params",
        "break_derive_from_cycle",
        "align_fk_max_value",
        "isolate_date_ranges",
        "semantic_upgrade",
        "fix_self_reference",
        "coerce_float_to_int",
        "align_group_generators",
        # From LLM healer (Layer 4):
        "adjust_params",
        "coerce_type",
        "strip_invalid_params",
        "fix_choice_typo",
        "llm_heal",
    }
)

# [Defense 7] RCE defense: forbid persistence of params whose values
# could carry arbitrary code (e.g., expression strings, lambda source,
# eval/exec payloads). These keys are stripped or refused before write.
# This is the SINGLE source of truth — diff_learner.py imports from here.
# Union of both previous lists to avoid any gap in coverage.
FORBIDDEN_PERSIST_KEYS = frozenset(
    {
        # Code execution primitives:
        "custom_function",
        "eval",
        "exec",
        "compile",
        "lambda",
        "__import__",
        "globals",
        "locals",
        # Attribute/system access:
        "getattr",
        "setattr",
        "delattr",
        # File / process / OS:
        "open",
        "subprocess",
        "os",
        "sys",
        # Expression source strings (core's ExpressionEngine entry point):
        "expression",
        "code",
    }
)


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

    def save(self, contracts: list[ContractViolation]) -> None:
        """Atomically save a list of contracts to the registry file.

        Defense 1: writes to a temp file first, then renames to the final
        path. This prevents partial writes from corrupting the registry.

        Note: this overwrites the entire registry with the given list.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in contracts]
        fd, tmp_path = tempfile.mkstemp(
            prefix=f"{self._path.name}.",
            suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def load(self, schema_hash: str | None = None) -> list[ContractViolation]:
        """Load contracts from the registry, optionally filtered by schema_hash.

        Defense 8: if ``schema_hash`` is provided, only entries with a
        matching hash are returned.

        Defense 7: tampered entries (forbidden keys / non-whitelisted
        strategy) are silently dropped at load time.
        """
        if not self._path.exists():
            return []
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to load learned contracts registry",
                path=str(self._path),
                error=str(exc),
            )
            return []

        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = [e for e in data if isinstance(e, dict)]
        elif isinstance(data, dict) and isinstance(data.get("contracts"), list):
            items = [e for e in data["contracts"] if isinstance(e, dict)]

        contracts: list[ContractViolation] = []
        for entry in items:
            if not self._is_safe_entry(entry):
                logger.warning(
                    "Defense 7: dropping tampered learned contract",
                    generator=entry.get("generator"),
                    strategy=entry.get("fix_strategy"),
                )
                continue
            try:
                cv = ContractViolation.from_dict(entry)
            except (KeyError, ValueError) as exc:
                logger.warning("Malformed registry entry skipped", error=str(exc))
                continue
            if schema_hash is not None and cv.schema_hash != schema_hash:
                continue
            contracts.append(cv)
        return contracts

    @staticmethod
    def _is_safe_entry(entry: dict[str, Any]) -> bool:
        """Defense 7 re-check at load time."""
        strategy = entry.get("fix_strategy", "")
        if strategy not in SAFE_FIX_STRATEGIES:
            return False
        fix_params = entry.get("fix_params", {}) or {}
        return all(key not in FORBIDDEN_PERSIST_KEYS for key in fix_params)

    def _load(self) -> None:
        """Load from disk; corrupt files are treated as empty.

        Supports both plain-list and wrapped-dict ``{"contracts": [...]}``
        formats for backward compatibility.
        """
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            items: list[dict[str, Any]] = []
            if isinstance(data, list):
                items = [e for e in data if isinstance(e, dict)]
            elif isinstance(data, dict) and isinstance(data.get("contracts"), list):
                items = [e for e in data["contracts"] if isinstance(e, dict)]
            for item in items:
                if not self._is_safe_entry(item):
                    continue
                self._contracts.add(ContractViolation.from_dict(item))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning(
                "Learned contracts registry corrupted, ignoring",
                error=str(e),
                path=str(self._path),
            )

    def _save(self) -> None:
        """Persist current contracts to disk as JSON (wrapped-dict format).

        Defense 1: writes to a temp file first, then renames to the final
        path. This prevents partial writes from corrupting the registry.
        """
        data = {
            "schema_hash": None,
            "contracts": [v.to_dict() for v in self._contracts],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f"{self._path.name}.",
            suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
