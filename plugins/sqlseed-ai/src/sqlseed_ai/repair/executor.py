"""Layer 3: RepairExecutor.

Applies repair strategies to violations, sorted by severity (crash first).

Spec reference: Section 5.5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed_ai.repair.models import AppliedFix, RepairResult
from sqlseed_ai.repair.strategies import REPAIR_STRATEGIES, RepairFn

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.validator.models import ViolationReport
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

logger = get_logger(__name__)

_SEVERITY_ORDER: dict[str, int] = {
    "crash": 0,
    "unique_unsatisfiable": 1,
    "semantic_error": 2,
}


class RepairExecutor:
    """Layer 3 main executor."""

    def __init__(self, strategies: dict[str, RepairFn] | None = None) -> None:
        self._strategies = strategies or REPAIR_STRATEGIES

    def repair(
        self,
        config: dict[str, Any],
        violations: list[ViolationReport],
        snapshot: SchemaSnapshot,
    ) -> RepairResult:
        """Apply repair strategies to violations, sorted by severity."""
        applied_fixes: list[AppliedFix] = []
        unfixable: list[ViolationReport] = []
        sorted_violations = self._sort_by_severity(violations)
        for violation in sorted_violations:
            strategy_name = violation.fix_hint
            if strategy_name is None or strategy_name not in self._strategies:
                unfixable.append(violation)
                continue
            for table_config in config.get("tables", []):
                if table_config["name"] != violation.table:
                    continue
                cols_to_fix = self._expand_composite_cols(violation, table_config)
                for col in cols_to_fix:
                    before = {**col}
                    ctx: dict[str, Any] = {
                        "table_schema": snapshot.tables.get(violation.table),
                        "table_config": table_config,
                        "column_type": snapshot.get_column_type(violation.table, col.get("name", "")),
                    }
                    try:
                        after = self._strategies[strategy_name](col, violation, ctx)
                        col.clear()
                        col.update(after)
                        applied_fixes.append(
                            AppliedFix(
                                table=violation.table,
                                columns=[col.get("name", "")],
                                fix_strategy=strategy_name,
                                before=before,
                                after=after,
                                violation_kind=violation.severity,
                            )
                        )
                    except Exception as e:
                        logger.warning(
                            "Repair strategy failed",
                            strategy=strategy_name,
                            error=str(e),
                        )
                        unfixable.append(violation)
        return RepairResult(config=config, applied_fixes=applied_fixes, unfixable=unfixable)

    @staticmethod
    def _sort_by_severity(
        violations: list[ViolationReport],
    ) -> list[ViolationReport]:
        return sorted(violations, key=lambda v: _SEVERITY_ORDER.get(v.severity, 99))

    @staticmethod
    def _expand_composite_cols(violation: ViolationReport, table_config: dict[str, Any]) -> list[dict[str, Any]]:
        """Return column dicts that match the violation's columns."""
        return [c for c in table_config.get("columns", []) if c.get("name") in violation.columns]
