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

    Combines four sub-checks:
    1. FK integrity: FK column max_value should not exceed parent PK range
       (currently optimistic — precise check deferred to LLM Healer).
    2. Composite UNIQUE: (placeholder for future expansion)
    3. Semantic relations: (placeholder for future expansion)
    4. derive_from DAG: detects self-references and 2-cycles.
    """

    def validate(
        self,
        table_config: dict[str, Any],
        table_schema: dict[str, Any],
        snapshot: SchemaSnapshot,
    ) -> list[ViolationReport]:
        """Return all cross-column violations for the given table config."""
        violations: list[ViolationReport] = []
        violations.extend(self._check_fk_integrity(table_config, snapshot))
        violations.extend(self._check_composite_unique(table_config, table_schema))
        violations.extend(self._check_semantic_relations(table_config, table_schema))
        violations.extend(self._check_derive_from_dag(table_config))
        return violations

    def _check_fk_integrity(
        self,
        table_config: dict[str, Any],
        snapshot: SchemaSnapshot,
    ) -> list[ViolationReport]:
        """Check FK column max_value does not exceed parent PK range.

        Currently optimistic — precise parent PK range check requires a DB
        query and is deferred to the LLM Healer (Layer 4) when the Fast
        Validator cannot resolve it. This stub returns no violations but
        guards against crashes when the table is missing from the snapshot.
        """
        result: list[ViolationReport] = []
        table_meta = snapshot.tables.get(table_config["name"])
        if table_meta is None:
            return result
        for fk in table_meta.foreign_keys:
            fk_cols = fk.get("columns") or []
            parent_table = fk.get("ref_table")
            if not (fk_cols and parent_table):
                continue
            for fk_col in fk_cols:
                col_config = next(
                    (c for c in table_config.get("columns", []) if c.get("name") == fk_col),
                    None,
                )
                if col_config is None:
                    continue
                params = col_config.get("params") or {}
                max_val = params.get("max_value")
                if max_val is None:
                    continue
                # Optimistic: only flag if max_val exceeds a reasonable bound
                # (precise parent PK range check requires DB query; defer to LLM Healer)
        return result

    def _check_composite_unique(
        self,
        table_config: dict[str, Any],
        table_schema: dict[str, Any],
    ) -> list[ViolationReport]:
        """Placeholder for composite UNIQUE cross-checks (future expansion)."""
        return []

    def _check_semantic_relations(
        self,
        table_config: dict[str, Any],
        table_schema: dict[str, Any],
    ) -> list[ViolationReport]:
        """Placeholder for semantic relation cross-checks (future expansion)."""
        return []

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
            derive_from = col.get("derive_from")
            if not derive_from:
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
                src_col = cols_by_name.get(src)
                if src_col:
                    src_df = src_col.get("derive_from")
                    if src_df:
                        src_df_list = [src_df] if isinstance(src_df, str) else list(src_df)
                        if col_name in src_df_list:
                            result.append(
                                ViolationReport(
                                    table=table_config["name"],
                                    columns=[col_name, src],
                                    constraint_type=ConstraintType.CHECK,
                                    severity="crash",
                                    fix_hint="break_derive_from_cycle",
                                    fix_params={"columns": [col_name, src]},
                                )
                            )
        return result
