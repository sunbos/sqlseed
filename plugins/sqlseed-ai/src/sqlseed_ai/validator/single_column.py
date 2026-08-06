"""2a: Single-column contract check (sparse matrix, O(N)~O(1)).

Iterates each column in the table config, queries the ContractResolver
for known violations, and runs a cardinality check for UNIQUE columns.

Spec reference: Section 4.3.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

from sqlseed_ai.contracts.matrix import ContractResolver, ViolationKind
from sqlseed_ai.validator.models import ConstraintType, ViolationReport

if TYPE_CHECKING:
    from sqlseed_ai.contracts.matrix import ContractViolation


def _to_num(raw: str) -> int | float:
    """Convert a numeric literal string to int (no decimal) or float."""
    return int(raw) if "." not in raw else float(raw)


def _extract_enum_values(expr: str, col_name: str) -> list[int | str] | None:
    """Extract the value set from a ``col IN (...)`` CHECK expression.

    Handles single- and double-quoted strings and bare int/float literals,
    e.g. ``role IN ('admin', 'user', 'guest')`` → ``['admin', 'user', 'guest']``
    or ``flag IN (0, 1)`` → ``[0, 1]``. Returns ``None`` when the expression
    does not contain an ``IN`` clause for ``col_name``.
    """
    m = re.search(
        rf"\b{re.escape(col_name)}\s+IN\s*\((.*?)\)",
        expr,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    inner = m.group(1)
    values: list[int | str] = []
    for q_single, q_double, num in re.findall(r"""'([^']*)'|"([^"]*)"|(-?\d+(?:\.\d+)?)""", inner):
        if q_single != "":
            values.append(q_single)
        elif q_double != "":
            values.append(q_double)
        elif num != "":
            values.append(_to_num(num))
    return values or None


def _extract_range_bounds(exprs: list[str], col_name: str) -> dict[str, int | float] | None:
    """Merge min/max bounds from a column's CHECK range expressions.

    Handles ``col >= X AND col <= Y``, ``col BETWEEN X AND Y``, and one-sided
    ``col >= X`` / ``col <= Y``. Multiple bounds are merged by taking the
    higher lower-bound and the lower upper-bound. Returns ``None`` if no
    range operator is found.
    """
    col = re.escape(col_name)
    min_val: int | float | None = None
    max_val: int | float | None = None
    for expr in exprs:
        m = re.search(
            rf"\b{col}\s+BETWEEN\s+(-?\d+(?:\.\d+)?)\s+AND\s+(-?\d+(?:\.\d+)?)",
            expr,
            re.IGNORECASE,
        )
        if m:
            lo, hi = _to_num(m.group(1)), _to_num(m.group(2))
            min_val = lo if min_val is None else max(min_val, lo)
            max_val = hi if max_val is None else min(max_val, hi)
        m = re.search(rf"\b{col}\s+>=\s*(-?\d+(?:\.\d+)?)", expr, re.IGNORECASE)
        if m:
            v = _to_num(m.group(1))
            min_val = v if min_val is None else max(min_val, v)
        m = re.search(rf"\b{col}\s+<=\s*(-?\d+(?:\.\d+)?)", expr, re.IGNORECASE)
        if m:
            v = _to_num(m.group(1))
            max_val = v if max_val is None else min(max_val, v)
    if min_val is None and max_val is None:
        return None
    result: dict[str, int | float] = {}
    if min_val is not None:
        result["min_value"] = min_val
    if max_val is not None:
        result["max_value"] = max_val
    return result


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
                            fix_params={"reason": f"cardinality {cardinality} < row_count {row_count}"},
                        )
                    )
            check_violation = self._check_constraint_compliance(col, col_name, table_config["name"], table_schema)
            if check_violation is not None:
                violations.append(check_violation)
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
            return int(62**max_length)
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

    def _check_constraint_compliance(
        self,
        col: dict[str, Any],
        col_name: str,
        table_name: str,
        table_schema: dict[str, Any],
    ) -> ViolationReport | None:
        """Flag generators that violate a column's CHECK expression values.

        The sparse matrix is a closed set of known-bad *type* combinations
        and cannot carry the values of a CHECK expression (its ``IN (...)``
        set or numeric range). This step parses the column's CHECK
        constraints and emits a targeted violation when the configured
        generator would produce out-of-range values:

        - ``string``/``text`` on a ``CHECK IN ('a','b',...)`` column →
          ``coerce_to_text_enum`` (with ``check_values``)
        - any non-boolean generator on a ``CHECK IN (0,1)`` column →
          ``coerce_to_boolean_enum``
        - a numeric generator whose min/max exceed the CHECK range bounds →
          ``align_check_bounds`` (with ``min_value``/``max_value``)

        Returns ``None`` when no conflict exists (correct generator already
        chosen, or no parseable single-column CHECK).
        """
        gen = col.get("generator", "")
        constraints = table_schema.get("constraints", [])
        check_exprs: list[str] = []
        for c in constraints:
            if c.get("type") != "check":
                continue
            expr = c.get("expression")
            if not isinstance(expr, str):
                continue
            cols = c.get("columns") or []
            # SQLite inline CHECKs report empty column_names, so fall back to
            # a word-boundary scan of the expression.
            if col_name in cols or re.search(rf"\b{re.escape(col_name)}\b", expr, re.IGNORECASE):
                check_exprs.append(expr)
        if not check_exprs:
            return None

        enum_values: list[int | str] | None = None
        for expr in check_exprs:
            enum_values = _extract_enum_values(expr, col_name)
            if enum_values:
                break
        if enum_values:
            if all(isinstance(v, str) for v in enum_values):
                if gen not in ("choice", "weighted_choice"):
                    return ViolationReport(
                        table=table_name,
                        columns=[col_name],
                        constraint_type=ConstraintType.CHECK,
                        severity="semantic_error",
                        fix_hint="coerce_to_text_enum",
                        fix_params={"check_values": list(enum_values)},
                    )
            elif all(v in (0, 1) for v in enum_values):
                if gen != "boolean":
                    return ViolationReport(
                        table=table_name,
                        columns=[col_name],
                        constraint_type=ConstraintType.CHECK,
                        severity="semantic_error",
                        fix_hint="coerce_to_boolean_enum",
                        fix_params={"check_values": list(enum_values)},
                    )
            # Numeric (non-boolean) enum: no dedicated strategy — leave as-is.
            return None

        bounds = _extract_range_bounds(check_exprs, col_name)
        if bounds and gen in ("integer", "random_int", "float", "random_float"):
            params = col.get("params") or {}
            cur_min = params.get("min_value")
            cur_max = params.get("max_value")
            conflict = False
            if "min_value" in bounds and (cur_min is None or cur_min < bounds["min_value"]):
                conflict = True
            if "max_value" in bounds and (cur_max is None or cur_max > bounds["max_value"]):
                conflict = True
            if conflict:
                return ViolationReport(
                    table=table_name,
                    columns=[col_name],
                    constraint_type=ConstraintType.CHECK,
                    severity="semantic_error",
                    fix_hint="align_check_bounds",
                    fix_params={k: v for k, v in bounds.items()},
                )
        return None

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
