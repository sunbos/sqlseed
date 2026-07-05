"""Layer 2 → Layer 3 bridge with incremental verification.

微调2 (Section 5.6): if all violations fixed, skip second global validate.
Only re-validate modified tables when partial fix.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed_ai.repair.executor import RepairExecutor
from sqlseed_ai.repair.models import RepairResult
from sqlseed_ai.validator.main import FastValidator

if TYPE_CHECKING:
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


class RepairPipeline:
    """Layer 2 → Layer 3 bridge."""

    def __init__(
        self,
        resolver: ContractResolver,
        db_path: str | None = None,
        url: str | None = None,
    ) -> None:
        self._validator = FastValidator(resolver, db_path=db_path, url=url)
        self._executor = RepairExecutor()

    def run(
        self,
        config: dict[str, Any],
        snapshot: SchemaSnapshot,
        fill_error: Exception | None = None,
        dialect: str = "sqlite",
    ) -> tuple[dict[str, Any], RepairResult]:
        """Validate → repair → (conditionally) re-validate."""
        validation = self._validator.validate(config, snapshot, fill_error, dialect)
        if validation.is_clean:
            return config, RepairResult(
                config=config, applied_fixes=[], unfixable=[]
            )

        repair_result = self._executor.repair(
            config, validation.violations, snapshot
        )

        # 微调2: only re-validate if not all fixed (partial fix case)
        if repair_result.applied_fixes and len(repair_result.applied_fixes) < len(
            validation.violations
        ):
            modified_tables = {f.table for f in repair_result.applied_fixes}
            modified_config: dict[str, Any] = {
                "tables": [
                    t
                    for t in config.get("tables", [])
                    if t["name"] in modified_tables
                ]
            }
            revalidation = self._validator.validate(
                modified_config, snapshot, None, dialect
            )
            if not revalidation.is_clean:
                repair_result.unfixable.extend(revalidation.violations)

        return config, repair_result
