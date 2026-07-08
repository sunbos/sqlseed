"""HealOrchestrator — coordinates 4-level LLM heal degradation.

Spec reference: Section 3.1 + 2.2 + 4.1.

Replaces ``Layer4Coordinator``. Routes LLM failures by type:
  CONTEXT_OVERFLOW / EMPTY_RESPONSE → Level 2 (column-level)
  JSON_FORMAT → Level 3 (compact, skip Level 2)
  SEMANTIC → Level 4 (deterministic degrade, skip Level 2/3)
  NETWORK → raise exception (not in degradation chain)

Pre-judgment: if token estimate > 60% of context window, skip Level 1.
"""

from __future__ import annotations

import copy
import time
from typing import TYPE_CHECKING, Any

from sqlseed_ai.healer.models import (
    DegradeReason,
    FailureType,
    HealAttempt,
    HealResult,
    SubgraphTask,
)
from sqlseed_ai.healer.oscillation import OscillationDetector

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.healer.context_detector import ContextWindowDetector
    from sqlseed_ai.healer.degrader import ProgressiveDegrader
    from sqlseed_ai.healer.failure_classifier import FailureClassifier
    from sqlseed_ai.healer.level1_subgraph_healer import Level1SubgraphHealer
    from sqlseed_ai.healer.level2_column_healer import Level2ColumnHealer
    from sqlseed_ai.healer.level3_compact_healer import Level3CompactHealer
    from sqlseed_ai.validator.models import ViolationReport
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

logger = get_logger(__name__)


class HealOrchestrator:
    """Coordinate 4-level LLM heal degradation with failure-type routing."""

    def __init__(
        self,
        *,
        snapshot: SchemaSnapshot,
        context_detector: ContextWindowDetector,
        failure_classifier: FailureClassifier,
        level1: Level1SubgraphHealer,
        level2: Level2ColumnHealer,
        level3: Level3CompactHealer,
        degrader: ProgressiveDegrader,
        validator: Any,  # FastValidator
        schema_hash: str = "",
        max_rounds: int = 3,
        time_budget_seconds: float = 60.0,
    ) -> None:
        self._snapshot = snapshot
        self._context_detector = context_detector
        self._failure_classifier = failure_classifier
        self._level1 = level1
        self._level2 = level2
        self._level3 = level3
        self._degrader = degrader
        self._validator = validator
        self._schema_hash = schema_hash
        self._max_rounds = max_rounds
        self._time_budget = time_budget_seconds
        self._oscillation = OscillationDetector()

    def heal(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
    ) -> HealResult:
        """Main entry: orchestrate 4-level degradation.

        Returns HealResult with the final config (repaired or degraded).
        Network errors propagate as RuntimeError (Section 5.3).
        """
        start = time.monotonic()
        attempts: list[HealAttempt] = []
        current_config = copy.deepcopy(config)
        current_violations = list(violations)
        table_name = task.tables[0] if task.tables else ""

        for round_num in range(1, self._max_rounds + 1):
            if time.monotonic() - start > self._time_budget:
                logger.warning("HealOrchestrator time budget exhausted", budget=self._time_budget)
                degraded_result = self._degrade_and_return(
                    current_config,
                    current_violations,
                    DegradeReason.TIME_BUDGET_EXHAUSTED,
                    attempts,
                    round_num,
                    start,
                )
                self._log_heal_complete(table_name, degraded_result, start)
                return degraded_result

            result = self._try_one_round(task, current_violations, current_config, attempts, round_num)

            if result.success:
                # Re-validate the patched config.
                if result.config_patch is not None:
                    current_config = self._merge_patch(current_config, result.config_patch)
                val_result = self._validator.validate(current_config, self._snapshot)
                new_violations = self._extract_violations(val_result)

                if not new_violations:
                    heal_result = HealResult(
                        config=current_config,
                        success=True,
                        level_used=result.level,
                        attempts=attempts,
                        total_attempts=round_num,
                        total_elapsed=time.monotonic() - start,
                    )
                    self._log_heal_complete(table_name, heal_result, start)
                    return heal_result

                # New violations — feed back into the loop.
                current_violations = new_violations
                if self._oscillation.check_and_record(current_violations):
                    logger.warning("Oscillation detected, degrading", round=round_num)
                    degraded_result = self._degrade_and_return(
                        current_config,
                        current_violations,
                        DegradeReason.LLM_OSCILLATION,
                        attempts,
                        round_num,
                        start,
                    )
                    self._log_heal_complete(table_name, degraded_result, start)
                    return degraded_result
                continue

            # Failure — classify and route.
            ftype = result.failure_type
            if ftype == FailureType.NETWORK:
                raise RuntimeError(f"LLM network error: {result.error}")

            # For non-network failures, the routing is handled inside
            # _try_one_round. If we reach here, all levels failed.
            degraded_result = self._degrade_and_return(
                current_config,
                current_violations,
                DegradeReason.LLM_FAILURE,
                attempts,
                round_num,
                start,
            )
            self._log_heal_complete(table_name, degraded_result, start)
            return degraded_result

        degraded_result = self._degrade_and_return(
            current_config,
            current_violations,
            DegradeReason.MAX_RETRIES_EXCEEDED,
            attempts,
            self._max_rounds,
            start,
        )
        self._log_heal_complete(table_name, degraded_result, start)
        return degraded_result

    @staticmethod
    def _log_heal_attempt(
        table_name: str,
        attempt: HealAttempt,
        column: str = "",
        next_level: int = 0,
    ) -> None:
        """Log a single heal attempt (Spec 5.5 — heal_attempt event).

        Records level, failure_type, latency, token estimate, and the next
        level to try (for diagnostics and post-hoc analysis).
        """
        logger.info(
            "heal_attempt",
            table=table_name,
            level=attempt.level,
            column=column or None,
            failure_type=attempt.failure_type.value if attempt.failure_type else None,
            latency_ms=attempt.latency_ms,
            token_estimate=attempt.token_estimate,
            next_level=next_level or None,
            error=attempt.error_message,
        )

    def _log_heal_complete(self, table_name: str, result: HealResult, start: float) -> None:
        """Log the final heal result (Spec 5.5 — heal_complete event)."""
        logger.info(
            "heal_complete",
            table=table_name,
            success=result.success,
            level_used=result.level_used,
            total_attempts=result.total_attempts,
            total_elapsed_ms=int((time.monotonic() - start) * 1000),
            degraded_columns=result.degraded_columns,
            failure_type=result.failure_type.value if result.failure_type else None,
            attempts=[
                {
                    "level": a.level,
                    "failure_type": a.failure_type.value if a.failure_type else None,
                    "latency_ms": a.latency_ms,
                    "token_estimate": a.token_estimate,
                }
                for a in result.attempts
            ],
        )

    def _try_one_round(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
        attempts: list[HealAttempt],
        round_num: int,
    ) -> _RoundResult:
        """Try Level 1 → (Level 2 | Level 3) → degrade for one round.

        Returns _RoundResult with success/failure + failure_type + level.
        """
        # Pre-judgment: skip Level 1 if prompt too large.
        l1_prompt = self._level1.build_prompt(task, violations, config)
        skip_l1 = self._context_detector.should_skip_level1(l1_prompt.system_prompt + l1_prompt.user_prompt)

        if not skip_l1:
            # Level 1: subgraph-level.
            l1_result = self._level1.heal(task, violations, config)
            l1_ftype = (
                None
                if l1_result.success
                else self._failure_classifier.classify(l1_result.error, l1_result.raw_response)
            )
            l1_attempt = HealAttempt(
                level=1,
                failure_type=l1_ftype,
                latency_ms=int(l1_result.elapsed_seconds * 1000),
                token_estimate=l1_result.prompt_tokens,
                error_message=str(l1_result.error) if l1_result.error else None,
            )
            attempts.append(l1_attempt)
            table_name = task.tables[0] if task.tables else ""
            # Spec 5.5: log heal_attempt with next_level routing hint.
            next_level = 0 if l1_result.success else self._next_level_after_l1(l1_ftype or FailureType.UNKNOWN)
            self._log_heal_attempt(table_name, l1_attempt, next_level=next_level)
            if l1_result.success:
                return _RoundResult(success=True, level=1, config_patch=l1_result.config_patch or {})

            # Classify failure.
            return self._route_after_l1_failure(
                task, violations, config, l1_ftype or FailureType.UNKNOWN, attempts, round_num
            )

        # Pre-judgment skipped Level 1 → go to Level 2.
        logger.info("Skipping Level 1 (pre-judgment: prompt too large)")
        return self._try_level2(task, violations, config, attempts, round_num)

    def _route_after_l1_failure(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
        ftype: FailureType,
        attempts: list[HealAttempt],
        round_num: int,
    ) -> _RoundResult:
        """Route to next level based on Level 1 failure type (Section 2.2)."""
        if ftype in (FailureType.CONTEXT_OVERFLOW, FailureType.EMPTY_RESPONSE):
            return self._try_level2(task, violations, config, attempts, round_num)
        if ftype == FailureType.JSON_FORMAT:
            return self._try_level3(task, violations, config, attempts, round_num, mode="compact")
        if ftype == FailureType.NETWORK:
            return _RoundResult(success=False, level=1, failure_type=FailureType.NETWORK)
        # SEMANTIC or UNKNOWN → degrade.
        return _RoundResult(success=False, level=1, failure_type=ftype)

    def _try_level2(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
        attempts: list[HealAttempt],
        round_num: int,
    ) -> _RoundResult:
        """Try Level 2: column-level healing for each violation column."""
        merged_patch: dict[str, Any] = {"tables": []}
        all_success = True
        any_success = False

        for v in violations:
            for col in v.columns:
                l2_result = self._level2.heal_column(v.table, col, v, config, self._snapshot)
                l2_ftype = (
                    None
                    if l2_result.success
                    else self._failure_classifier.classify(l2_result.error, l2_result.raw_response)
                )
                l2_attempt = HealAttempt(
                    level=2,
                    failure_type=l2_ftype,
                    latency_ms=int(l2_result.elapsed_seconds * 1000),
                    token_estimate=l2_result.prompt_tokens,
                    error_message=str(l2_result.error) if l2_result.error else None,
                )
                attempts.append(l2_attempt)
                # Spec 5.5: log heal_attempt per column with next_level hint.
                next_level = 0 if l2_result.success else (3 if l2_ftype == FailureType.CONTEXT_OVERFLOW else 4)
                self._log_heal_attempt(v.table, l2_attempt, column=col, next_level=next_level)
                if l2_result.success and l2_result.config_patch:
                    # Merge single-column patch into merged_patch.
                    self._merge_column_patch(merged_patch, v.table, l2_result.config_patch)
                    any_success = True
                else:
                    all_success = False
                    # Classify failure for routing.
                    if l2_ftype == FailureType.CONTEXT_OVERFLOW:
                        # Single-column prompt overflow → Level 3.
                        return self._try_level3(task, violations, config, attempts, round_num, mode="compact")

        if all_success and any_success:
            return _RoundResult(success=True, level=2, config_patch=merged_patch)
        if any_success:
            # Partial success — return what we have; remaining columns
            # will be caught by re-validation and degraded.
            return _RoundResult(success=True, level=2, config_patch=merged_patch)
        return _RoundResult(success=False, level=2, failure_type=FailureType.UNKNOWN)

    def _try_level3(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        config: dict[str, Any],
        attempts: list[HealAttempt],
        round_num: int,
        mode: str,
    ) -> _RoundResult:
        """Try Level 3: compact then ultra_compact."""
        l3_result = self._level3.heal_compact(task, violations, config, mode=mode)  # type: ignore[arg-type]
        l3_ftype = (
            None if l3_result.success else self._failure_classifier.classify(l3_result.error, l3_result.raw_response)
        )
        l3_attempt = HealAttempt(
            level=3,
            failure_type=l3_ftype,
            latency_ms=int(l3_result.elapsed_seconds * 1000),
            token_estimate=l3_result.prompt_tokens,
            error_message=str(l3_result.error) if l3_result.error else None,
        )
        attempts.append(l3_attempt)
        table_name = task.tables[0] if task.tables else ""
        # Spec 5.5: log heal_attempt. next_level = 3 if retrying ultra_compact, else 4 (degrade).
        next_level = 0 if l3_result.success else (3 if mode == "compact" else 4)
        self._log_heal_attempt(table_name, l3_attempt, next_level=next_level)
        if l3_result.success:
            return _RoundResult(success=True, level=3, config_patch=l3_result.config_patch or {})

        # If compact failed, try ultra_compact.
        if mode == "compact":
            return self._try_level3(task, violations, config, attempts, round_num, mode="ultra_compact")

        # ultra_compact also failed → degrade.
        return _RoundResult(success=False, level=3, failure_type=l3_ftype or FailureType.UNKNOWN)

    @staticmethod
    def _next_level_after_l1(ftype: FailureType) -> int:
        """Determine next level after Level 1 failure (Spec 2.2 routing)."""
        if ftype in (FailureType.CONTEXT_OVERFLOW, FailureType.EMPTY_RESPONSE):
            return 2
        if ftype == FailureType.JSON_FORMAT:
            return 3
        if ftype == FailureType.NETWORK:
            return 0  # raise, no next level
        # SEMANTIC or UNKNOWN → degrade
        return 4

    def _degrade_and_return(
        self,
        config: dict[str, Any],
        violations: list[ViolationReport],
        reason: DegradeReason,
        attempts: list[HealAttempt],
        round_num: int,
        start: float,
    ) -> HealResult:
        """Invoke ProgressiveDegrader and build the final HealResult."""
        failed_cols = self._collect_failed_columns(violations)
        if not failed_cols:
            return HealResult(
                config=config,
                success=False,
                level_used=4,
                attempts=attempts,
                total_attempts=round_num,
                total_elapsed=time.monotonic() - start,
            )
        failed_map = {c: reason for c in failed_cols}
        new_config, _ = self._degrader.degrade(config, failed_map, column_groups=[])
        return HealResult(
            config=new_config,
            success=False,
            level_used=4,
            degraded_columns=failed_cols,
            degrade_reasons=failed_map,
            attempts=attempts,
            total_attempts=round_num,
            total_elapsed=time.monotonic() - start,
        )

    @staticmethod
    def _extract_violations(val_result: Any) -> list[ViolationReport]:
        """Extract violations list from a ValidationResult or list."""
        if hasattr(val_result, "violations"):
            return list(val_result.violations)
        return list(val_result or [])

    @staticmethod
    def _merge_patch(config: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """Merge a healer-produced patch into the current config."""
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
    def _merge_column_patch(merged: dict[str, Any], table_name: str, col_patch: dict[str, Any]) -> None:
        """Merge a single-column patch into the merged patch dict."""
        # Find or create the table entry.
        for t in merged.get("tables", []):
            if t["name"] == table_name:
                t["columns"].append(col_patch)
                return
        merged["tables"].append({"name": table_name, "columns": [col_patch]})

    @staticmethod
    def _collect_failed_columns(violations: list[ViolationReport]) -> list[str]:
        """Flatten columns from all violations (deduped, table-prefixed)."""
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


class _RoundResult:
    """Internal result of one round attempt (not exported)."""

    __slots__ = ("config_patch", "error", "failure_type", "level", "success")

    def __init__(
        self,
        *,
        success: bool,
        level: int,
        config_patch: dict[str, Any] | None = None,
        failure_type: FailureType | None = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.level = level
        self.config_patch = config_patch
        self.failure_type = failure_type
        self.error = error
