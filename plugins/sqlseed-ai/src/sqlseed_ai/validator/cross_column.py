"""2b: Cross-column constraint check.

Validates cross-column relationships: FK integrity, composite UNIQUE,
semantic relations, and derive_from DAG cycle detection.

Spec reference: Section 4.4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed_ai.validator.models import ConstraintType, ViolationReport

if TYPE_CHECKING:
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


class CrossColumnValidator:
    """2b: Cross-column constraint check.

    Detects unsupported individual UNIQUE flags on composite-index columns,
    derive_from self-references and two-column dependency cycles.
    Database FK failures are handled by FastValidator's dialect/shadow checks.
    """

    def validate(
        self,
        table_config: dict[str, Any],
        table_schema: dict[str, Any],
        snapshot: SchemaSnapshot,
    ) -> list[ViolationReport]:
        """Return all cross-column violations for the given table config."""
        violations: list[ViolationReport] = []
        violations.extend(self._check_composite_unique(table_config, table_schema))
        violations.extend(self._check_derive_from_dag(table_config))
        return violations

    def _check_composite_unique(
        self,
        table_config: dict[str, Any],
        table_schema: dict[str, Any],
    ) -> list[ViolationReport]:
        """Flag columns marked unique:true that only appear in composite UNIQUE (Rule #31).

        A composite UNIQUE constraint (e.g., ``UNIQUE(tenant_id, email)``)
        does NOT make any individual column unique. If the LLM marks such a
        column as ``constraints: {unique: true}``, flag it for stripping.
        """
        result: list[ViolationReport] = []
        unique_indexes = table_schema.get("unique_indexes") or []
        if not isinstance(unique_indexes, list):
            return result

        if not (composite_only := self._composite_only_columns(unique_indexes)):
            return result

        for col in table_config.get("columns", []):
            if (col_name := col.get("name", "")) not in composite_only:
                continue
            constraints = col.get("constraints") or {}
            if isinstance(constraints, dict) and constraints.get("unique"):
                result.append(
                    ViolationReport(
                        table=table_config["name"],
                        columns=[col_name],
                        constraint_type=ConstraintType.UNIQUE,
                        severity="semantic_error",
                        fix_hint="strip_composite_unique",
                        fix_params={"reason": "column only in composite UNIQUE"},
                    )
                )
        return result

    @staticmethod
    def _composite_only_columns(unique_indexes: list[Any]) -> set[str]:
        """Separate columns covered only by composite UNIQUE constraints."""
        single_unique_cols: set[str] = set()
        composite_unique_cols: set[str] = set()
        for idx in unique_indexes:
            if not isinstance(idx, dict):
                continue
            cols = idx.get("columns") or []
            if not isinstance(cols, list):
                continue
            if len(cols) == 1:
                single_unique_cols.add(cols[0])
            elif len(cols) > 1:
                composite_unique_cols.update(cols)

        # Columns in composite UNIQUE but NOT in single-col UNIQUE
        return composite_unique_cols - single_unique_cols

    def _check_derive_from_dag(
        self,
        table_config: dict[str, Any],
    ) -> list[ViolationReport]:
        """Detect derive_from self-references and 2-cycles (A→B→A).

        Adversarial fix: derive_from can be either a string (single dep) or
        a list (multi dep). Use strict type checking: ``==`` for str, ``in``
        for list. Substring matching on a str derive_from would cause false
        positives (e.g., "total" matching "tot").
        """
        result: list[ViolationReport] = []
        cols_by_name = {c.get("name"): c for c in table_config.get("columns", [])}
        for col_name, col in cols_by_name.items():
            if not (derive_from := col.get("derive_from")):
                continue
            derive_from_list = [derive_from] if isinstance(derive_from, str) else list(derive_from)
            for src in derive_from_list:
                if src == col_name:
                    result.append(
                        ViolationReport(
                            table=table_config["name"],
                            columns=[col_name],
                            constraint_type=ConstraintType.CHECK,
                            severity="crash",
                            fix_hint="fix_self_reference",
                            fix_params={"column": col_name},
                        )
                    )
                # Check 2-cycle: col derives from src, src derives from col
                cycle = self._two_column_cycle(table_config["name"], col_name, src, cols_by_name.get(src))
                if cycle is not None:
                    result.append(cycle)
        return result

    @staticmethod
    def _two_column_cycle(
        table_name: str, column_name: str, source: str, source_column: dict[str, Any] | None
    ) -> ViolationReport | None:
        """Report a two-column cycle only when the source explicitly depends on this column."""
        if not source_column or not (dependencies := source_column.get("derive_from")):
            return None
        sources = [dependencies] if isinstance(dependencies, str) else list(dependencies)
        if column_name not in sources:
            return None
        return ViolationReport(
            table=table_name,
            columns=[column_name, source],
            constraint_type=ConstraintType.CHECK,
            severity="crash",
            fix_hint="break_derive_from_cycle",
            fix_params={"columns": [column_name, source]},
        )
