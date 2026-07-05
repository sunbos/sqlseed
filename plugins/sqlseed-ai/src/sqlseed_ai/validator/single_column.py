"""2a: Single-column contract check (sparse matrix, O(N)~O(1)).

Iterates each column in the table config, queries the ContractResolver
for known violations, and runs a cardinality check for UNIQUE columns.

Spec reference: Section 4.3.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sqlseed_ai.contracts.matrix import ContractResolver, ViolationKind
from sqlseed_ai.validator.models import ConstraintType, ViolationReport

if TYPE_CHECKING:
    from sqlseed_ai.contracts.matrix import ContractViolation


class SingleColumnValidator:
    """2a: Single-column contract check.

    Combines sparse-matrix lookup (via :class:`ContractResolver`) with a
    cardinality check for UNIQUE columns. The cardinality check uses
    generator-specific formulas with robust defaults so missing params
    never crash the validator (Spec 微调3).
    """

    def __init__(self, resolver: ContractResolver) -> None:
        self._resolver = resolver

    def validate(
        self,
        table_config: dict[str, Any],
        table_schema: dict[str, Any],
        row_count: int,
    ) -> list[ViolationReport]:
        """Return violations for each column in ``table_config``."""
        violations: list[ViolationReport] = []
        for col in table_config.get("columns", []):
            col_name = col.get("name", "")
            col_type = self._extract_col_type(col_name, table_schema)
            constraints = self._extract_constraints(col_name, table_schema)
            violation = self._resolver.check(
                generator=col.get("generator", ""),
                column_type=col_type,
                constraints=constraints,
                config={
                    **col,
                    "row_count": row_count,
                    "name": col_name,
                    "pool_size": self._pool_size(col),
                },
            )
            if violation:
                violations.append(
                    ViolationReport(
                        table=table_config["name"],
                        columns=[col_name],
                        constraint_type=self._map_constraint_type(violation),
                        severity=self._map_severity(violation.kind),
                        fix_hint=violation.fix_strategy,
                        fix_params=violation.fix_params,
                    )
                )
            if "UNIQUE" in constraints:
                cardinality = self._compute_cardinality(col, row_count)
                if cardinality < row_count:
                    violations.append(
                        ViolationReport(
                            table=table_config["name"],
                            columns=[col_name],
                            constraint_type=ConstraintType.UNIQUE,
                            severity="unique_unsatisfiable",
                            fix_hint="upgrade_to_template",
                            fix_params={
                                "reason": f"cardinality {cardinality} < row_count {row_count}"
                            },
                        )
                    )
        return violations

    def _compute_cardinality(self, col: dict[str, Any], row_count: int) -> int | float:
        """Compute generator cardinality with robust defaults (微调3).

        Returns ``float('inf')`` for effectively-infinite generators
        (template), so ``cardinality < row_count`` is always False.
        """
        gen = col.get("generator", "")
        params = col.get("params") or {}
        if gen == "choice":
            choices = params.get("choices") or []
            return len(choices)
        if gen == "template":
            return float("inf")
        if gen == "integer":
            min_val = params.get("min_value", 0) or 0
            max_val = params.get("max_value", 9999) or 9999
            return max_val - min_val + 1
        if gen == "string":
            max_length = int(params.get("max_length", 10))
            return int(62 ** max_length)
        return row_count  # optimistic

    def _pool_size(self, col: dict[str, Any]) -> int:
        params = col.get("params") or {}
        if "choices" in params:
            return len(params["choices"])
        return 0

    def _extract_col_type(
        self,
        col_name: str,
        table_schema: dict[str, Any],
    ) -> str:
        for col in table_schema.get("columns", []):
            if col.get("name") == col_name:
                return str(col.get("type", "ANY")).upper()
        return "ANY"

    def _extract_constraints(
        self,
        col_name: str,
        table_schema: dict[str, Any],
    ) -> frozenset[str]:
        result: set[str] = set()
        for c in table_schema.get("constraints", []):
            cols = c.get("columns") or []
            if col_name in cols:
                ctype = c.get("type")
                if ctype == "unique":
                    result.add("UNIQUE")
                elif ctype == "check":
                    result.add("CHECK")
                elif ctype == "primary_key":
                    result.add("UNIQUE")
                    result.add("NOT_NULL")
        # NOT NULL from column definition
        for col in table_schema.get("columns", []):
            if col.get("name") == col_name and not col.get("nullable", True):
                result.add("NOT_NULL")
        return frozenset(result)

    @staticmethod
    def _map_constraint_type(v: ContractViolation) -> ConstraintType:
        """Map ViolationKind to ConstraintType for ViolationReport."""
        if v.kind == ViolationKind.UNIQUE_UNSATISFIABLE:
            return ConstraintType.UNIQUE
        if v.kind == ViolationKind.CRASH:
            return ConstraintType.CHECK  # type compat crash
        return ConstraintType.CHECK

    @staticmethod
    def _map_severity(kind: ViolationKind) -> Literal["crash", "semantic_error", "unique_unsatisfiable"]:
        """Map ViolationKind to severity literal accepted by ViolationReport.

        ``CONDITIONAL`` violations are folded into ``semantic_error`` because
        the severity field does not have a ``conditional`` literal — the
        ``kind`` field on the source ContractViolation already preserves
        that distinction for downstream consumers.
        """
        if kind == ViolationKind.CRASH:
            return "crash"
        if kind == ViolationKind.UNIQUE_UNSATISFIABLE:
            return "unique_unsatisfiable"
        return "semantic_error"  # SEMANTIC_ERROR + CONDITIONAL
