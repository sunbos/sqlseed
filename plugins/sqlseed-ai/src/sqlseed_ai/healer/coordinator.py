"""Layer 4 Coordinator — Kubernetes-style reconcile loop.

Spec reference: Section 6.1 (Controller pattern), 6.5 (oscillation),
6.6 (progressive degrade), 6.7 (diff learning).

The coordinator owns cross-attempt state (oscillation history, attempt
count, time budget). For each attempt it:
  1. Calls LLMHealer.heal() with current config + violations.
  2. If success: applies the patch, re-validates via Layer 2.
     - If no new violations: returns success.
     - If new violations: feeds them back into the loop.
  3. If failure: records error, checks oscillation, degrades if needed.
  4. On any successful fix: calls DiffLearner.learn_from_fix() (4e).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sqlseed_ai.healer.degrader import ProgressiveDegrader
from sqlseed_ai.healer.diff_learner import DiffLearner
from sqlseed_ai.healer.models import DegradeReason, HealResult, SubgraphTask
from sqlseed_ai.healer.oscillation import OscillationDetector
from sqlseed_ai.repair.models import AppliedFix

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.contracts.matrix import ContractViolation
    from sqlseed_ai.healer.llm_healer import LLMHealer
    from sqlseed_ai.validator.models import ViolationReport
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

logger = get_logger(__name__)


class Layer4Coordinator:
    """Reconcile loop for LLM-driven healing (Layer 4)."""

    def __init__(
        self,
        *,
        healer: LLMHealer,
        validator: Any,  # FastValidator (Layer 2) or mock
        snapshot: SchemaSnapshot,
        max_attempts: int = 3,
        schema_hash: str = "",
        time_budget_seconds: float = 60.0,
    ) -> None:
        self._healer = healer
        self._validator = validator
        self._snapshot = snapshot
        self._max_attempts = max_attempts
        self._schema_hash = schema_hash
        self._time_budget = time_budget_seconds
        self._oscillation = OscillationDetector()
        self._degrader = ProgressiveDegrader(snapshot)
        self._learner = DiffLearner(schema_hash=schema_hash)

    def reconcile(
        self,
        task: SubgraphTask,
        config: dict[str, Any],
        initial_violations: list[ViolationReport],
        column_groups: list[Any] | None = None,
    ) -> HealResult:
        """Run the reconcile loop and return the final HealResult."""
        start = time.monotonic()
        current_config = config
        current_violations = list(initial_violations)
        all_fixes: list[AppliedFix] = []
        learned: list[ContractViolation] = []
        attempt_num = 0

        while attempt_num < self._max_attempts:
            attempt_num += 1
            # Time budget check
            if time.monotonic() - start > self._time_budget:
                logger.warning("Layer 4 time budget exhausted", budget=self._time_budget)
                return self._degrade_and_return(
                    current_config,
                    current_violations,
                    {c: DegradeReason.TIME_BUDGET_EXHAUSTED for c in self._collect_failed_columns(current_violations)},
                    all_fixes,
                    learned,
                    attempt_num,
                    start,
                    column_groups,
                )

            # Call LLM healer (4a + 4b)
            attempt = self._healer.heal(task, current_violations, current_config)
            if not attempt.success:
                logger.warning(
                    "LLM healer failed",
                    attempt=attempt_num,
                    error=attempt.error,
                )
                # If this was the last attempt, degrade
                if attempt_num == self._max_attempts:
                    return self._degrade_and_return(
                        current_config,
                        current_violations,
                        {
                            c: DegradeReason.MAX_RETRIES_EXCEEDED
                            for c in self._collect_failed_columns(current_violations)
                        },
                        all_fixes,
                        learned,
                        attempt_num,
                        start,
                        column_groups,
                    )
                continue

            # Apply the patch (merge into current_config)
            current_config = self._merge_patch(current_config, attempt.config_patch)
            # Record an AppliedFix for Diff learning
            fix = AppliedFix(
                table=task.tables[0] if task.tables else "",
                columns=self._collect_failed_columns(current_violations),
                fix_strategy="llm_heal",
                before={},
                after=attempt.config_patch,
                violation_kind=(current_violations[0].constraint_type.value if current_violations else "unknown"),
                success=True,
            )
            all_fixes.append(fix)

            # Re-validate (Layer 2). FastValidator.validate() requires a
            # snapshot positional arg and returns a ValidationResult
            # dataclass (not a list). Without passing snapshot the call
            # raises TypeError; without unwrapping .violations the
            # truthy dataclass makes the success branch unreachable.
            val_result = self._validator.validate(current_config, self._snapshot)
            new_violations = (
                list(val_result.violations) if hasattr(val_result, "violations") else list(val_result or [])
            )
            if not new_violations:
                # Success — try to learn from each applied fix
                for f in all_fixes:
                    contract = self._learner.learn_from_fix(
                        f,
                        generator="unknown",
                        column_type="ANY",
                        constraints=frozenset(),
                    )
                    if contract is not None:
                        learned.append(contract)
                return HealResult(
                    config=current_config,
                    applied_fixes=all_fixes,
                    degraded_columns=[],
                    degrade_reasons={},
                    learned_contracts=learned,
                    total_attempts=attempt_num,
                    total_elapsed=time.monotonic() - start,
                )

            # New violations — feed back into the loop
            current_violations = new_violations

            # Oscillation check (4c) — only after a successful patch
            # application. Checking at loop start would misfire when the
            # LLM healer failed (attempt.success=False) and violations
            # didn't change, falsely detecting "oscillation".
            if self._oscillation.check_and_record(current_violations):
                logger.warning(
                    "Oscillation detected, degrading failing columns",
                    attempt=attempt_num,
                )
                return self._degrade_and_return(
                    current_config,
                    current_violations,
                    {c: DegradeReason.LLM_OSCILLATION for c in self._collect_failed_columns(current_violations)},
                    all_fixes,
                    learned,
                    attempt_num,
                    start,
                    column_groups,
                )

        # Exhausted all attempts without success
        return self._degrade_and_return(
            current_config,
            current_violations,
            {c: DegradeReason.MAX_RETRIES_EXCEEDED for c in self._collect_failed_columns(current_violations)},
            all_fixes,
            learned,
            attempt_num,
            start,
            column_groups,
        )

    def _degrade_and_return(
        self,
        config: dict[str, Any],
        violations: list[ViolationReport],
        failed: dict[str, DegradeReason],
        applied: list[AppliedFix],
        learned: list[ContractViolation],
        attempt_num: int,
        start: float,
        column_groups: list[Any] | None,
    ) -> HealResult:
        """Invoke ProgressiveDegrader and build the final HealResult."""
        if not failed:
            return HealResult(
                config=config,
                applied_fixes=applied,
                degraded_columns=[],
                degrade_reasons={},
                learned_contracts=learned,
                total_attempts=attempt_num,
                total_elapsed=time.monotonic() - start,
            )
        new_config, degrade_fixes = self._degrader.degrade(config, failed, column_groups=column_groups or [])
        applied.extend(degrade_fixes)
        return HealResult(
            config=new_config,
            applied_fixes=applied,
            degraded_columns=list(failed.keys()),
            degrade_reasons=failed,
            learned_contracts=learned,
            total_attempts=attempt_num,
            total_elapsed=time.monotonic() - start,
        )

    @staticmethod
    def _merge_patch(config: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """Merge a healer-produced patch into the current config.

        For each table in the patch, replace matching columns in the config
        with the patch's version. Tables not in the patch are preserved.
        """
        import copy

        new_config = copy.deepcopy(config)
        patch_tables = {t["name"]: t for t in patch.get("tables", [])}
        for table_cfg in new_config.get("tables", []):
            name = table_cfg["name"]
            if name not in patch_tables:
                continue
            patch_cols = {c["name"]: c for c in patch_tables[name].get("columns", [])}
            new_columns = []
            for col in table_cfg.get("columns", []):
                if col["name"] in patch_cols:
                    # Preserve _degraded marker if present (don't un-degrade)
                    degraded = col.get("_degraded", False)
                    new_col = copy.deepcopy(patch_cols[col["name"]])
                    if degraded:
                        new_col["_degraded"] = True
                    new_columns.append(new_col)
                else:
                    new_columns.append(col)
            table_cfg["columns"] = new_columns
        return new_config

    @staticmethod
    def _collect_failed_columns(violations: list[ViolationReport]) -> list[str]:
        """Flatten the columns from all violation reports (deduped).

        Includes table prefix when available to avoid cross-table collisions
        in multi-table SCC scenarios where two tables share a column name
        (e.g. both have 'id'). The ``table:column`` key format is parsed by
        :meth:`ProgressiveDegrader._expand_composite_groups` to filter
        failures per-table before degradation.
        """
        seen: list[str] = []
        for v in violations:
            table = getattr(v, "table", "") or ""
            for c in v.columns:
                if not c:
                    continue
                key = f"{table}:{c}" if table else c
                if key not in seen:
                    seen.append(key)
        return seen
