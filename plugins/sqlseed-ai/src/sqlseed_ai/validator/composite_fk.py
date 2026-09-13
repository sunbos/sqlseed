"""[Defense 5] Composite FK coordinator.

Identifies composite FKs, binds them as :class:`ColumnGroup`, and ensures
coordinated generation/degrade. When any member of a composite FK fails,
ALL members degrade together to a coordinated fallback (e.g., joint SELECT
from parent) so the composite FK stays satisfiable.

Spec reference: Section 4.6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed_ai.validator.models import ColumnGroup, ConstraintType, ViolationReport

if TYPE_CHECKING:
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


class CompositeFKCoordinator:
    """Identify composite FK, bind coordinated groups.

    A composite FK is one whose ``constrained_columns`` list has more than
    one entry. Single-column FKs do not need coordinated degrade.
    """

    def identify_groups(self, snapshot: SchemaSnapshot) -> list[ColumnGroup]:
        """Scan snapshot for composite FKs and return a ColumnGroup per FK."""
        groups: list[ColumnGroup] = []
        for table in snapshot.tables.values():
            for fk in table.foreign_keys:
                cols = fk.get("columns") or []
                if len(cols) <= 1:
                    continue
                group_id = f"{table.name}_{'_'.join(cols)}_fk"
                groups.append(
                    ColumnGroup(
                        group_id=group_id,
                        columns=list(cols),
                        parent_table=fk.get("ref_table", ""),
                        parent_columns=list(fk.get("ref_columns") or []),
                        degrade_together=True,
                    )
                )
        return groups

    def validate_group(
        self,
        group: ColumnGroup,
        table_config: dict[str, Any],
    ) -> ViolationReport | None:
        """Check that all group members use the same generator.

        Returns a ViolationReport with ``fix_hint="align_group_generators"``
        if members disagree on generator choice. Returns None if aligned or
        if the table_config doesn't include all group members (incomplete
        config is not a coordination violation).
        """
        cols = [c for c in table_config.get("columns", []) if c.get("name") in group.columns]
        if len(cols) != len(group.columns):
            return None
        generators = {c.get("generator") for c in cols}
        if len(generators) > 1:
            return ViolationReport(
                table=table_config["name"],
                columns=list(group.columns),
                constraint_type=ConstraintType.FK,
                severity="semantic_error",
                is_composite=True,
                fix_hint="align_group_generators",
                fix_params={"group_id": group.group_id},
            )
        return None

    def coordinate_degrade(
        self,
        group: ColumnGroup,
        degraded_col: str,
    ) -> list[str]:
        """Return the list of columns that should degrade together.

        If ``degraded_col`` is a member of a ``degrade_together`` group,
        all group members degrade. Otherwise, only the single column
        degrades (preserving the existing behavior for non-group columns).
        """
        if group.degrade_together and degraded_col in group.columns:
            return list(group.columns)
        return [degraded_col]
