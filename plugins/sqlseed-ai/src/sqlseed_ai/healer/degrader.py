"""Progressive Degrade (Layer 4d) — fall back to Core 9-level mapper when LLM fails.

Defense 4 (cascade degrade): when a column degrades, its downstream (FK children
and derive_from dependents) must also degrade to preserve referential integrity
and expression correctness.

Defense 5 (composite FK coordinator): if a column is part of a composite FK
group, the entire group degrades together.

Section 14.2 (cycle termination): an explicit ``visited`` set guarantees that
cyclic dependencies (A derives B, B derives A) cannot cause stack overflow,
even if the ``_degraded`` marker were somehow bypassed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed_ai.healer.models import DegradeReason
from sqlseed_ai.repair.models import AppliedFix

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.validator.models import ColumnGroup
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

logger = get_logger(__name__)


class ProgressiveDegrader:
    """Fall back failed LLM-generated columns to the Core 9-level mapper.

    The degrader mutates a copy of the per-table config dict, marking each
    degraded column with ``_degraded=True`` and stripping LLM-only fields
    (``generator``/``params``/``derive_from``/``expression``) so that the
    Core mapper can re-infer a safe default. Downstream columns (FK children
    and derive_from dependents) are cascaded via :meth:`_cascade_degrade`.
    """

    def __init__(self, snapshot: SchemaSnapshot) -> None:
        self._snapshot = snapshot

    def degrade(
        self,
        config: dict[str, Any],
        failed_columns: dict[str, DegradeReason],
        column_groups: list[ColumnGroup],
    ) -> tuple[dict[str, Any], list[AppliedFix]]:
        """Degrade failed columns + cascade downstream + composite FK groups.

        Args:
            config: Per-table config dict with structure
                ``{"tables": [{"name": str, "columns": list[dict]}]}``.
            failed_columns: Map of failed column name -> reason.
            column_groups: Composite FK groups (Defense 5).

        Returns:
            Tuple of (new_config, applied_fixes). The input config is not
            mutated; a deep copy is returned.
        """
        import copy

        new_config = copy.deepcopy(config)
        applied: list[AppliedFix] = []
        visited: set[tuple[str, str]] = set()

        # Phase 1: degrade failed columns + cascade
        for table_cfg in new_config.get("tables", []):
            table_name = table_cfg["name"]
            columns = table_cfg.get("columns", [])
            col_index = {c["name"]: c for c in columns}

            # Expand failed_columns with composite FK group members
            expanded_failed = self._expand_composite_groups(failed_columns, column_groups, table_name)

            for col_name, reason in expanded_failed.items():
                key = (table_name, col_name)
                if key in visited:
                    continue
                self._cascade_degrade(
                    table_name=table_name,
                    col_name=col_name,
                    reason=reason,
                    columns=columns,
                    col_index=col_index,
                    column_groups=column_groups,
                    applied=applied,
                    visited=visited,
                )

        return new_config, applied

    def _expand_composite_groups(
        self,
        failed_columns: dict[str, DegradeReason],
        column_groups: list[ColumnGroup],
        table_name: str,
    ) -> dict[str, DegradeReason]:
        """Defense 5: if any column in a composite FK group fails, the whole group fails.

        Filters table-prefixed keys (``table:column``) to only include
        columns belonging to ``table_name``, preventing cross-table
        collisions in multi-table SCC scenarios where two tables share a
        column name (e.g. both have 'id'). Bare column names (no prefix)
        are kept as-is for backward compatibility.
        """
        expanded: dict[str, DegradeReason] = {}
        for key, reason in failed_columns.items():
            if ":" in key:
                tbl, col = key.split(":", 1)
                if tbl == table_name:
                    expanded[col] = reason
            else:
                expanded[key] = reason
        for group in column_groups:
            if any(col in expanded for col in group.columns):
                for col in group.columns:
                    if col not in expanded:
                        expanded[col] = DegradeReason.CASCADE  # cascade origin
        return expanded

    def _cascade_degrade(
        self,
        *,
        table_name: str,
        col_name: str,
        reason: DegradeReason,
        columns: list[dict[str, Any]],
        col_index: dict[str, dict[str, Any]],
        column_groups: list[ColumnGroup],
        applied: list[AppliedFix],
        visited: set[tuple[str, str]],
    ) -> None:
        """Recursively degrade ``col_name`` and its downstream dependents.

        Section 14.2: ``visited`` is the dual-layer safety net that
        guarantees termination even if the ``_degraded`` marker is bypassed.
        """
        key = (table_name, col_name)
        if key in visited:
            return
        visited.add(key)

        col = col_index.get(col_name)
        if col is None or col.get("_degraded"):
            return

        # Snapshot before-state for Diff learning (Defense 4 audit trail)
        before_snapshot = {
            k: col.get(k)
            for k in (
                "generator",
                "params",
                "derive_from",
                "expression",
                "faker_method",
                "mimesis_method",
                "native_params",
            )
        }

        # Mark degraded and strip LLM-only fields
        col["_degraded"] = True
        col["degrade_reason"] = reason.value
        for field_name in (
            "generator",
            "params",
            "derive_from",
            "expression",
            "faker_method",
            "mimesis_method",
            "native_params",
        ):
            col.pop(field_name, None)

        applied.append(
            AppliedFix(
                table=table_name,
                columns=[col_name],
                fix_strategy="progressive_degrade",
                before=before_snapshot,
                after={"_degraded": True, "degrade_reason": reason.value},
                violation_kind=reason.value,
                success=True,
            )
        )

        # Cascade to downstream: derive_from dependents + composite FK group
        downstream = self._find_downstream_inclusive(col_name, columns, column_groups)
        for ds_col_name in downstream:
            ds_col = col_index.get(ds_col_name)
            if ds_col and not ds_col.get("_degraded"):
                self._cascade_degrade(
                    table_name=table_name,
                    col_name=ds_col_name,
                    reason=DegradeReason.CASCADE,
                    columns=columns,
                    col_index=col_index,
                    column_groups=column_groups,
                    applied=applied,
                    visited=visited,
                )

    @staticmethod
    def _find_downstream_inclusive(
        col_name: str,
        columns: list[dict[str, Any]],
        column_groups: list[ColumnGroup],
    ) -> list[str]:
        """Find columns that depend on ``col_name`` via derive_from or composite FK.

        Adversarial fix (reviewer feedback): ``derive_from`` in YAML may be
        either a list (``[col_a, col_b]``) or a single string (``subtotal``).
        Using ``col_name in (c.get("derive_from") or [])`` directly would do
        substring matching when ``derive_from`` is a string (e.g.,
        ``"id" in "subtotal_id"`` returns True — wrong!). We must normalize
        to list first.
        """
        downstream: list[str] = []
        # derive_from dependents (with strict type-aware comparison)
        for c in columns:
            derive_from = c.get("derive_from")
            if isinstance(derive_from, str):
                is_dep = derive_from == col_name
            elif isinstance(derive_from, list):
                is_dep = col_name in derive_from
            else:
                is_dep = False
            if is_dep:
                downstream.append(c["name"])
        # composite FK group members (if any column in the group fails, all degrade)
        for group in column_groups:
            if col_name in group.columns:
                for other in group.columns:
                    if other != col_name:
                        downstream.append(other)
        return downstream
