"""Explicit, read-only replacement planning; execution options are not core config."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlseed.config.models import GeneratorConfig

    from sqlseed_web.state import Connection


def normalize_execution(value: Any = None) -> dict[str, Any]:
    """Keep destructive options explicit and reject misspelled/unknown flags."""
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {"mode", "reset_identity"}:
        raise ValueError("执行选项只支持 mode 与 reset_identity")
    mode = value.get("mode", "append")
    reset = value.get("reset_identity", False)
    if mode not in ("append", "replace_selected") or not isinstance(reset, bool):
        raise ValueError("执行方式必须为 append 或 replace_selected，重置 ID 必须为布尔值")
    if reset and mode != "replace_selected":
        raise ValueError("只有清空所选表时才能重置 ID")
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
                    f"{table_config.name} 启用了从现有数据增强规则，清空会移除其来源；请关闭增强或使用追加。",
                    table=table_config.name,
                )
            )
    return issues


def _table_replacement_issues(
    tables: dict[str, Any], selected: set[str], sqlite: bool, execution: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for name, table in tables.items():
        for fk in table["foreign_keys"]:
            if fk["ref_schema"] not in (None, "main") and sqlite:
                continue
            if fk["ref_table"] not in selected:
                continue
            if name not in selected:
                issues.append(
                    _plan_issue(
                        "external_incoming_fk",
                        f"未选表 {name} 引用 {fk['ref_table']}，清空会影响所选范围外的数据；请一并选择相关表或使用追加。",
                        table=name,
                    )
                )
            elif name == fk["ref_table"] and not fk["nullable"]:
                issues.append(
                    _plan_issue(
                        "self_reference_after_clear",
                        f"{name} 的自引用字段不可空，清空后没有可用首条来源，不能安全重建。",
                        table=name,
                    )
                )
        if (
            name in selected
            and not execution["reset_identity"]
            and any(column.get("is_rowid_alias") and not column["is_autoincrement"] for column in table["columns"])
        ):
            issues.append(
                _plan_issue(
                    "rowid_restarts_on_clear",
                    f"{name} 使用普通 SQLite INTEGER 主键；清空后数据库可能自然从 1 分配，与重置 AUTOINCREMENT 选项无关。",
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
                            f"未选表 {name} 通过配置关联引用 {association.source_table}，请一并选择或使用追加。",
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
                    f"{trigger['tbl_name']} 存在触发器 {trigger['name']}，暂不能保证重建操作仅影响所选表；请使用追加。",
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
                    f"{name} 存在自引用 ON DELETE RESTRICT，不能保证整表删除顺序；请使用追加。",
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
                    "replacement_not_supported", "当前仅验证了 SQLite 的整次事务清空与回滚；此连接暂只支持追加生成。"
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
                    "identity_reset_not_supported", "所选表没有可重置的 SQLite AUTOINCREMENT 序列，请关闭重置 ID。"
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
