"""Explicit, read-only replacement planning; execution options are not core config."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from sqlseed_web.messages import message as tr

if TYPE_CHECKING:
    from sqlseed.config.models import GeneratorConfig

    from sqlseed_web.state import Connection


def normalize_execution(value: Any = None) -> dict[str, Any]:
    """Keep destructive options explicit and reject misspelled/unknown flags."""
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {"mode", "reset_identity"}:
        raise ValueError(tr("backend.workbench_execution.execution_options_support_only_mode_and_reset"))
    mode = value.get("mode", "append")
    reset = value.get("reset_identity", False)
    if mode not in ("append", "replace_selected") or not isinstance(reset, bool):
        raise ValueError(tr("backend.workbench_execution.execution_mode_must_be_append_or_replace"))
    if reset and mode != "replace_selected":
        raise ValueError(tr("backend.workbench_execution.ids_can_be_reset_only_when_clearing"))
    return {"mode": mode, "reset_identity": reset}


def _plan_issue(code: str, message: str, *, table: str = "", severity: str = "error") -> dict[str, Any]:
    return {"code": code, "message": message, "table": table, "severity": severity}


def _enrichment_issues(config: GeneratorConfig) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for table_config in config.tables:
        if table_config.enrich:
            issues.append(
                _plan_issue(
                    "replacement_enrich_not_supported",
                    tr(
                        "backend.workbench_execution.enriches_rules_from_existing_data_clearing_would",
                        p1=table_config.name,
                    ),
                    table=table_config.name,
                )
            )
    return issues


def _incoming_replacement_issues(
    name: str, table: dict[str, Any], selected: set[str], sqlite: bool
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for fk in table["foreign_keys"]:
        if fk["ref_schema"] not in (None, "main") and sqlite:
            continue
        if fk["ref_table"] not in selected:
            continue
        if name not in selected:
            issues.append(
                _plan_issue(
                    "external_incoming_fk",
                    tr(
                        "backend.workbench_execution.unselected_table_references_clearing_would_affect_data",
                        p1=name,
                        p2=fk["ref_table"],
                    ),
                    table=name,
                )
            )
        elif name == fk["ref_table"] and not fk["nullable"]:
            issues.append(
                _plan_issue(
                    "self_reference_after_clear",
                    tr("backend.workbench_execution.has_a_non_nullable_self_reference_and", p1=name),
                    table=name,
                )
            )
    return issues


def _table_replacement_issues(
    tables: dict[str, Any], selected: set[str], sqlite: bool, execution: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for name, table in tables.items():
        issues.extend(_incoming_replacement_issues(name, table, selected, sqlite))
        if (
            name in selected
            and not execution["reset_identity"]
            and any(column.get("is_rowid_alias") and not column["is_autoincrement"] for column in table["columns"])
        ):
            issues.append(
                _plan_issue(
                    "rowid_restarts_on_clear",
                    tr("backend.workbench_execution.uses_a_regular_sqlite_integer_primary_key", p1=name),
                    table=name,
                    severity="warning",
                )
            )
    return issues


def _association_replacement_issues(
    config: GeneratorConfig, selected: set[str], tables: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for association in config.associations:
        if association.source_table in selected:
            for name in association.target_tables:
                if name in tables and name not in selected:
                    issues.append(
                        _plan_issue(
                            "external_incoming_association",
                            tr(
                                "backend.workbench_execution.unselected_table_references_through_a_configured_association",
                                p1=name,
                                p2=association.source_table,
                            ),
                            table=name,
                        )
                    )
    return issues


def _sqlite_replacement_issues(
    conn: Connection, tables: dict[str, Any], order: list[str], selected: set[str]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    # Trigger side effects cannot be bounded by FK metadata or safely
    # inferred by parsing arbitrary SQL. No trigger-text allowlist.
    for trigger in conn.orchestrator.query("SELECT name, tbl_name FROM sqlite_master WHERE type = 'trigger'"):
        if trigger["tbl_name"] in selected:
            issues.append(
                _plan_issue(
                    "replacement_trigger_not_supported",
                    tr(
                        "backend.workbench_execution.has_trigger_rebuilding_cannot_be_guaranteed_to",
                        p1=trigger["tbl_name"],
                        p2=trigger["name"],
                    ),
                    table=trigger["tbl_name"],
                )
            )
    for name in order:
        if tables[name]["row_count"] and any(
            fk["table"] == name and str(fk["on_delete"]).upper() == "RESTRICT"
            for fk in conn.orchestrator.query("SELECT * FROM pragma_foreign_key_list(?)", (name,))
        ):
            issues.append(
                _plan_issue(
                    "self_reference_delete_restrict",
                    tr("backend.workbench_execution.has_a_self_reference_with_on_delete", p1=name),
                    table=name,
                )
            )
    return issues


def build_execution_plan(
    conn: Connection,
    config: GeneratorConfig,
    schema: dict[str, Any],
    order: list[str],
    execution: dict[str, Any],
    config_hash: str,
) -> dict[str, Any]:
    """Describe physical delete scope and gate unverified database behavior."""
    replacing = execution["mode"] == "replace_selected"
    sqlite = schema["dialect"] == "sqlite"
    selected = set(order)
    tables = {table["name"]: table for table in schema["tables"]}
    reset_supported = sqlite and any(column["is_autoincrement"] for name in order for column in tables[name]["columns"])
    issues: list[dict[str, Any]] = []

    if replacing:
        if not sqlite:
            issues.append(
                _plan_issue(
                    "replacement_not_supported",
                    tr("backend.workbench_execution.transactional_clearing_and_rollback_are_verified_only"),
                )
            )
        issues.extend(_enrichment_issues(config))
        issues.extend(_table_replacement_issues(tables, selected, sqlite, execution))
        issues.extend(_association_replacement_issues(config, selected, tables))
        if sqlite:
            issues.extend(_sqlite_replacement_issues(conn, tables, order, selected))
        if execution["reset_identity"] and not reset_supported:
            issues.append(
                _plan_issue(
                    "identity_reset_not_supported",
                    tr("backend.workbench_execution.the_selected_tables_have_no_resettable_sqlite"),
                )
            )
    plan: dict[str, Any] = {
        "ok": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
        "mode": execution["mode"],
        "execution": execution,
        "delete_order": list(reversed(order)) if replacing else [],
        "clear_tables": [{"name": name, "row_count": tables[name]["row_count"]} for name in reversed(order)]
        if replacing
        else [],
        "reset_identity_supported": reset_supported,
        "atomic": replacing and sqlite,
    }
    binding = {
        "plan": plan,
        "config_hash": config_hash,
        "schema_hash": schema["schema_hash"],
        "target_key": schema["target_key"],
    }
    plan["plan_hash"] = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return plan
