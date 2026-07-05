"""Layer 2 main validator: orchestrates 2a + 2b + dialect + composite FK + shadow scan.

Spec reference: Section 4.7, 14.3.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed_ai.validator.composite_fk import CompositeFKCoordinator
from sqlseed_ai.validator.cross_column import CrossColumnValidator
from sqlseed_ai.validator.dialect_parser import DialectErrorParser
from sqlseed_ai.validator.models import ConstraintType, ValidationResult
from sqlseed_ai.validator.shadow_fk_scan import ShadowFKScanner
from sqlseed_ai.validator.single_column import SingleColumnValidator

if TYPE_CHECKING:
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


class FastValidator:
    """Layer 2 main validator.

    Orchestrates the five Phase 1 components:

    - :class:`SingleColumnValidator` (2a): per-column contract + cardinality check.
    - :class:`CrossColumnValidator` (2b): FK integrity + derive_from DAG cycle detection.
    - :class:`DialectErrorParser` (Defense 3): normalize DBAPI exceptions to ViolationReport.
    - :class:`ShadowFKScanner` (Section 14.3): localize SQLite FK violation column.
    - :class:`CompositeFKCoordinator` (Defense 5): identify + validate composite FK groups.
    """

    def __init__(
        self,
        resolver: ContractResolver,
        db_path: str | None = None,
        url: str | None = None,
    ) -> None:
        self._single = SingleColumnValidator(resolver)
        self._cross = CrossColumnValidator()
        self._composite_fk = CompositeFKCoordinator()
        self._db_path = db_path
        self._url = url

    def validate(
        self,
        config: dict[str, Any],
        snapshot: SchemaSnapshot,
        fill_error: Exception | None = None,
        dialect: str = "sqlite",
        batch: list[dict[str, Any]] | None = None,
    ) -> ValidationResult:
        """Run all Phase 1 validation checks and return aggregated result."""
        all_violations: list[Any] = []
        default_count = config.get("default_count", 1000)

        for table_config in config.get("tables", []):
            table_meta = snapshot.tables.get(table_config["name"])
            if table_meta is not None:
                table_schema: dict[str, Any] = {
                    "columns": [
                        {"name": c, "type": table_meta.column_types[c]}
                        for c in table_meta.columns
                    ],
                    "constraints": table_meta.constraints,
                }
            else:
                table_schema = {"columns": [], "constraints": []}
            row_count = table_config.get("count", default_count)
            all_violations.extend(self._single.validate(table_config, table_schema, row_count))
            all_violations.extend(self._cross.validate(table_config, table_schema, snapshot))

        if fill_error is not None:
            report = DialectErrorParser.parse(
                fill_error, dialect, table=None, snapshot=snapshot
            )
            if report is not None:
                # Section 14.3: shadow scan for SQLite FK with empty columns
                if (
                    report.constraint_type == ConstraintType.FK
                    and not report.columns
                    and dialect == "sqlite"
                    and batch is not None
                ):
                    scanner = ShadowFKScanner(
                        db_path=self._db_path, snapshot=snapshot, url=self._url
                    )
                    report = scanner.scan(report, batch)
                all_violations.append(report)

        groups = self._composite_fk.identify_groups(snapshot)
        for group in groups:
            for table_config in config.get("tables", []):
                if table_config["name"] == group.parent_table:
                    continue
                v = self._composite_fk.validate_group(group, table_config)
                if v is not None:
                    all_violations.append(v)

        return ValidationResult(violations=all_violations, column_groups=groups)
