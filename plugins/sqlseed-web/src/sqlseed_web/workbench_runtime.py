"""Offline plan validation and server-owned multi-table execution for the workbench."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.engine import make_url
from sqlalchemy.exc import StatementError
from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.config.models import (
    ColumnAssociation,
    ColumnConfig,
    ColumnConstraintsConfig,
    CustomColumnMappings,
    ExactColumnMappingRule,
    GeneratorConfig,
    PatternColumnMappingRule,
    TableConfig,
)
from sqlseed.core.column_dag import ColumnDAG
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.stream import GenerationBudgetExceededError, GenerationCancelledError
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from sqlseed.generators._dispatch import GeneratorDispatchMixin

from sqlseed_web.runtime_lifecycle import start_background
from sqlseed_web.settings_environment import package_availability
from sqlseed_web.state import Connection, UIState, state
from sqlseed_web.workbench_execution import build_execution_plan, normalize_execution
from sqlseed_web.workbench_schema import inspect_connection
from sqlseed_web.workbench_store import WorkspaceStore, get_store

logger = get_logger(__name__)


class WorkbenchError(ValueError):
    """An actionable request error with a stable code and HTTP status."""

    def __init__(self, message: str, *, code: str = "invalid_config", status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _redact_query_credentials(message: str) -> str:
    """Consume each query field once, including incomplete keys containing '?'."""
    field_pattern = re.compile(r"[?&][^=&\s]*=?")
    value_pattern = re.compile(r"[^&\s'\")]+")
    parts: list[str] = []
    cursor = copied = 0
    while field := field_pattern.search(message, cursor):
        cursor = field.end()
        key = field.group()
        if not key.endswith("=") or not re.search(
            r"password|passwd|pwd|secret|token|credential|key|passfile", key, re.IGNORECASE
        ):
            continue
        value = value_pattern.match(message, cursor)
        if value is not None:
            parts.extend((message[copied:cursor], "***"))
            cursor = copied = value.end()
    return "".join(parts) + message[copied:]


def public_error(exc: Exception) -> str:
    """Avoid exposing connection credentials or SQLAlchemy parameter dumps."""
    if isinstance(exc, StatementError) and exc.orig is not None:
        message = str(exc.orig)
    else:
        message = str(exc)
    message = message.split("\n[SQL:", 1)[0].split("\n[parameters:", 1)[0]
    # A scheme can only start at a word boundary; do not retry inside long words.
    message = re.sub(r"(?<!\w)(\w+(?:\+\w+)?://)[^\s/@]+@", r"\1***@", message)
    message = _redact_query_credentials(message)
    return message[:2000]


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _identity(target: str) -> str:
    if "://" not in target:
        return str(Path(target).expanduser().resolve())
    url = make_url(target)
    database = url.database
    if url.get_backend_name() == "sqlite" and database and database != ":memory:":
        return str(Path(database).expanduser().resolve())
    secret_keys = [
        key
        for key in url.query
        if re.search(r"password|passwd|pwd|secret|token|credential|key|passfile", key, re.IGNORECASE)
    ]
    return url._replace(password=None).difference_update_query(secret_keys).render_as_string(hide_password=False)


def _reject_extra(value: Any, fields: Any, path: str) -> None:
    if isinstance(value, dict):
        extra = set(value) - set(fields)
        if extra:
            raise WorkbenchError(f"{path} 包含未知字段：{', '.join(sorted(extra))}", code="unknown_field")


def _validate_keys(raw: dict[str, Any]) -> None:
    _reject_extra(raw, GeneratorConfig.model_fields, "配置")
    for table in raw.get("tables", []) or []:
        _reject_extra(table, TableConfig.model_fields, "table")
        if isinstance(table, dict):
            for column in table.get("columns", []) or []:
                if isinstance(column, dict):
                    _reject_extra(column.get("constraints"), ColumnConstraintsConfig.model_fields, "constraints")
    for association in raw.get("associations", []) or []:
        _reject_extra(association, ColumnAssociation.model_fields, "association")
    mappings = raw.get("custom_column_mappings")
    _reject_extra(mappings, CustomColumnMappings.model_fields, "custom_column_mappings")
    if isinstance(mappings, dict):
        for rule in (mappings.get("exact") or {}).values():
            _reject_extra(rule, ExactColumnMappingRule.model_fields, "custom mapping")
        for rule in mappings.get("pattern", []) or []:
            _reject_extra(rule, PatternColumnMappingRule.model_fields, "custom pattern")


def bind_document(conn: Connection, document: dict[str, Any]) -> GeneratorConfig:
    """Validate the complete core model and bind only the explicitly selected target."""
    _validate_keys(document)
    db_path, url = document.get("db_path"), document.get("url")
    if db_path is not None and url is not None:
        raise WorkbenchError("db_path 与 url 只能提供一个", code="target_mismatch")
    for supplied in (db_path, url):
        if supplied is not None and _identity(str(supplied)) != _identity(conn.target):
            raise WorkbenchError("配置目标与当前连接不匹配，请明确选择相同目标", code="target_mismatch", status=409)
    raw = {key: value for key, value in document.items() if key not in {"db_path", "url"}}
    raw.setdefault("provider", conn.provider)
    raw.setdefault("locale", conn.locale)
    raw["url" if "://" in conn.target else "db_path"] = conn.target
    try:
        return GeneratorConfig.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise WorkbenchError(public_error(exc)) from exc


def normalize_document(conn: Connection, document: dict[str, Any]) -> dict[str, Any]:
    """Round-trip all core fields while omitting the connection and its credentials."""
    return bind_document(conn, document).model_dump(mode="json", exclude={"db_path", "url"})


def parse_document(conn: Connection, text: str) -> dict[str, Any]:
    """Parse safe YAML (including JSON), then apply core's configuration model."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WorkbenchError(f"无法解析 YAML/JSON：{public_error(exc)}", code="parse_error") from exc
    if not isinstance(raw, dict):
        raise WorkbenchError("配置必须是 YAML/JSON object", code="parse_error")
    return normalize_document(conn, raw)


def export_document(conn: Connection, document: dict[str, Any]) -> dict[str, Any]:
    """Export an executable core config, with URL passwords and secret query options removed."""
    config = bind_document(conn, document).model_dump(mode="json", exclude_none=True)
    omitted = False
    if config.get("url"):
        url = make_url(config["url"])
        secret_keys = [
            key
            for key in url.query
            if re.search(r"password|passwd|pwd|secret|token|credential|key|passfile", key, re.IGNORECASE)
        ]
        omitted = url.password is not None or bool(secret_keys)
        config["url"] = (
            url._replace(password=None).difference_update_query(secret_keys).render_as_string(hide_password=False)
        )
    return {
        "yaml": yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        "json": json.dumps(config, ensure_ascii=False, indent=2),
        "credentials_omitted": omitted,
    }


def _issue(issues: list[dict[str, Any]], code: str, message: str, *, severity: str = "error", **context: Any) -> None:
    issues.append({"severity": severity, "code": code, "message": message, **context})


def _layers(dependencies: dict[str, set[str]]) -> tuple[list[str], list[list[str]]]:
    pending = {name: set(parents) for name, parents in dependencies.items()}
    layers: list[list[str]] = []
    while pending:
        layer = [name for name, parents in pending.items() if not parents]
        if not layer:
            break
        layers.append(layer)
        for name in layer:
            del pending[name]
        for parents in pending.values():
            parents.difference_update(layer)
    return [name for layer in layers for name in layer], layers


def _source_values(orch: DataOrchestrator, table: str, columns: list[str]) -> list[dict[str, Any]]:
    quoted = [quote_identifier(column) for column in columns]
    return orch.query(
        f"SELECT DISTINCT {', '.join(quoted)} FROM {quote_identifier(table)} "
        f"WHERE {' AND '.join(f'{column} IS NOT NULL' for column in quoted)} "
        f"ORDER BY {', '.join(quoted)} LIMIT 10000"
    )


def _can_omit(column: dict[str, Any], table: dict[str, Any], dialect: str) -> bool:
    return bool(
        column.get("default") is not None
        or column.get("is_autoincrement")
        or column.get("is_computed")
        or column.get("is_rowid_alias")
    )


def _runtime_columns(config: GeneratorConfig, table: TableConfig, orch: DataOrchestrator) -> list[ColumnConfig]:
    """Protect matched custom rules from core's subsequent schema fallback.

    Explicit per-table columns retain precedence. The mapper still selects the
    applicable exact/pattern rule, including its normal name and type priority.
    """
    columns = list(table.columns)
    mappings = config.custom_column_mappings
    if mappings is None:
        return columns
    configured = {column.name for column in columns}
    for info in orch.get_column_info(table.name):
        if info.name in configured:
            continue
        names = {info.name.lower(), orch._mapper._to_snake_case(info.name)}
        candidates: list[Any] = [rule for name, rule in mappings.exact.items() if name.lower() in names]
        candidates.extend(rule for rule in mappings.pattern if any(re.match(rule.pattern, name) for name in names))
        mapped = orch.map_column(info)
        if any(mapped.generator_name == rule.generator and mapped.params == rule.params for rule in candidates):
            columns.append(
                ColumnConfig(
                    name=info.name,
                    generator=mapped.generator_name,
                    params=dict(mapped.params),
                    null_ratio=mapped.null_ratio,
                )
            )
    return columns


def _column_issues(config: GeneratorConfig, tables: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    known = set(GeneratorDispatchMixin.GENERATOR_MAP) | {"skip", "foreign_key", "foreign_key_or_integer"}
    for table in config.tables:
        if table.name not in tables:
            _issue(issues, "unknown_table", "数据表不存在", table=table.name)
            continue
        if table.clear_before:
            _issue(
                issues,
                "clear_not_supported",
                "工作台尚未支持经过外键校验的清空计划；请关闭 clear_before",
                table=table.name,
            )
        if table.transform:
            _issue(
                issues,
                "transform_not_supported",
                "工作台尚未支持执行服务器 Python transform；配置会保留在导出中",
                table=table.name,
            )
        columns = {column["name"]: column for column in tables[table.name]["columns"]}
        seen: set[str] = set()
        for column in table.columns:
            context = {"table": table.name, "column": column.name}
            if column.name in seen:
                _issue(issues, "duplicate_column", "列配置重复", **context)
            seen.add(column.name)
            if column.provider is not None and column.provider != config.provider:
                _issue(
                    issues,
                    "column_provider_not_supported",
                    "当前 core 使用全局 provider；暂不支持不同的每列 provider",
                    **context,
                )
            if column.generator and column.generator not in known:
                _issue(issues, "unknown_generator", f"未知 generator：{column.generator}", **context)
            info = columns.get(column.name)
            if info is None:
                _issue(issues, "unknown_column", "列已不存在，请刷新 schema 并修正配置", **context)
                continue
            single_unique = [constraint["columns"] for constraint in tables[table.name]["unique_constraints"]]
            single_unique.append(tables[table.name]["primary_key"])
            is_unique = [column.name] in single_unique or bool(column.constraints and column.constraints.unique)
            if is_unique and column.null_ratio == 0:
                choices = column.params.get("choices", column.params.get("weighted_choices"))
                if column.generator in {"choice", "weighted_choice"} and isinstance(choices, (list, dict)):
                    available = len({_hash(value) for value in choices})
                    if available < table.count:
                        _issue(
                            issues,
                            "unique_domain_exhausted",
                            f"显式候选值只有 {available} 个，无法生成 {table.count} 个唯一值",
                            **context,
                        )
                minimum, maximum = column.params.get("min_value"), column.params.get("max_value")
                if (
                    column.generator == "integer"
                    and isinstance(minimum, int)
                    and isinstance(maximum, int)
                    and maximum - minimum + 1 < table.count
                ):
                    _issue(issues, "unique_domain_exhausted", "显式整数范围不足以生成所需的唯一值", **context)
            if column.null_ratio > 0 and not info.get("nullable", True):
                _issue(issues, "not_null", "NOT NULL 列不能设置 null_ratio > 0", **context)
            dialect = make_url(config.url).get_backend_name() if config.url else "sqlite"
            can_skip = _can_omit(info, tables[table.name], dialect)
            if column.generator == "skip" and not info.get("nullable", True) and not can_skip:
                _issue(issues, "required_column", "没有默认值的 NOT NULL 列不能跳过", **context)
            sources = column.derive_from
            for source in [sources] if isinstance(sources, str) else sources or []:
                if source not in columns:
                    _issue(issues, "unknown_derive_source", f"派生来源列不存在：{source}", **context)
            if column.expression:
                try:
                    expression = ast.parse(column.expression, mode="eval")
                    allowed_calls = set(ExpressionEngine.SAFE_FUNCTIONS) | {"lookup"}
                    for call in ast.walk(expression):
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Name)
                            and call.func.id not in allowed_calls
                        ):
                            _issue(
                                issues,
                                "unknown_expression_function",
                                f"不支持的 expression 函数：{call.func.id}",
                                **context,
                            )
                except SyntaxError as exc:
                    _issue(issues, "invalid_expression", public_error(exc), **context)
    if config.snapshot_dir:
        _issue(
            issues,
            "snapshot_not_supported",
            "工作台使用持久化运行记录，尚未支持 snapshot_dir 文件写出；配置会保留在导出中",
        )
    if config.custom_column_mappings:
        mappings = config.custom_column_mappings
        for generator in [
            *[rule.generator for rule in mappings.exact.values()],
            *[rule.generator for rule in mappings.pattern],
        ]:
            if generator not in known:
                _issue(issues, "unknown_generator", f"自定义映射包含未知 generator：{generator}")
        for rule in mappings.pattern:
            try:
                re.compile(rule.pattern)
            except re.error as exc:
                _issue(issues, "invalid_pattern", public_error(exc))


def _dependency_plan(
    config: GeneratorConfig, schema: dict[str, Any], orch: DataOrchestrator, issues: list[dict[str, Any]]
) -> tuple[list[str], list[list[str]], set[str], dict[str, Any]]:
    tables = {table["name"]: table for table in schema["tables"]}
    selected = {table.name for table in config.tables}
    dependencies = {table.name: set[str]() for table in config.tables if table.name in tables}
    deferred: set[str] = set()
    evidence: dict[str, Any] = {
        "row_counts": {name: table["row_count"] for name, table in tables.items()},
        "source_checks": [],
    }

    def source(target: str, parent: str, columns: list[str], nullable: bool, column: str) -> None:
        context = {"table": target, "column": column, "source_table": parent}
        if parent not in tables or any(name not in {c["name"] for c in tables[parent]["columns"]} for name in columns):
            _issue(issues, "invalid_parent_source", "引用的来源表或列不存在", **context)
            return
        values = _source_values(orch, parent, columns)
        evidence["source_checks"].append(
            {
                **context,
                "source_columns": columns,
                "has_values": bool(values),
                "row_count": tables[parent]["row_count"],
                "selected": parent in selected,
                "nullable": nullable,
            }
        )
        evidence[f"{parent}:{','.join(columns)}"] = _hash(values)
        if parent != target and parent in dependencies:
            dependencies[target].add(parent)
        if not values:
            if parent == target:
                if not nullable:
                    _issue(issues, "self_reference_no_seed", "空表的 NOT NULL 自引用缺少有效初始父行", **context)
                elif len(columns) > 1:
                    _issue(issues, "composite_self_reference", "当前 core 未保证组合自引用的第二阶段回填", **context)
                else:
                    _issue(
                        issues,
                        "self_reference_backfill",
                        "可空自引用先生成 NULL，再由 core 回填已生成父行",
                        severity="warning",
                        **context,
                    )
            elif parent in selected:
                deferred.add(target)
                _issue(
                    issues,
                    "preview_requires_parent",
                    "父表当前没有可用值；执行时先填父表，预览无法提供完整关联样例",
                    severity="warning",
                    **context,
                )
            elif nullable:
                _issue(
                    issues,
                    "nullable_parent_empty",
                    "父表没有可用值，core 将生成 NULL 外键",
                    severity="warning",
                    **context,
                )
            else:
                _issue(
                    issues,
                    "missing_parent_source",
                    "非空外键/关联没有可用来源，请将父表加入计划或先准备有效父行",
                    **context,
                )

    for name in dependencies:
        for fk in tables[name]["foreign_keys"]:
            if fk.get("ref_schema") not in (None, "", "public", "main"):
                _issue(issues, "cross_schema_fk", "当前 core 尚未保证跨 schema 外键生成", table=name)
                continue
            if len(fk["columns"]) > 2:
                _issue(issues, "composite_fk_width", "当前 core 尚未保证三列及以上组合外键的元组配对", table=name)
                continue
            source(name, fk["ref_table"], fk["ref_columns"], fk["nullable"], ",".join(fk["columns"]))
    for association in config.associations:
        if association.strategy != "shared_pool":
            _issue(issues, "association_strategy", "当前 core 尚未区分 random 关联策略，请使用 shared_pool")
        for name in association.target_tables:
            if name not in tables or association.column_name not in {c["name"] for c in tables[name]["columns"]}:
                _issue(
                    issues,
                    "invalid_association_target",
                    "关联目标表或列不存在",
                    table=name,
                    column=association.column_name,
                )
            elif name in dependencies:
                source(
                    name,
                    association.source_table,
                    [association.source_column or association.column_name],
                    False,
                    association.column_name,
                )
    order, layers = _layers(dependencies)
    if len(order) != len(dependencies):
        _issue(issues, "cross_table_cycle", "跨表循环需要通用 backfill；当前工作台不能安全执行该计划")
    return order, layers, deferred, evidence


def _sample_issues(
    table: dict[str, Any],
    samples: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    *,
    dialect: str,
    excluded: set[str] | None = None,
) -> None:
    excluded = excluded or set()
    for column in table["columns"]:
        name = column["name"]
        if name in excluded or column.get("nullable", True):
            continue
        can_skip = _can_omit(column, table, dialect)
        if any(row.get(name) is None and (name in row or not can_skip) for row in samples):
            _issue(issues, "not_null_sample", "实际生成的样例违反 NOT NULL 约束", table=table["name"], column=name)
    unique_groups = [constraint["columns"] for constraint in table["unique_constraints"]]
    if table["primary_key"]:
        unique_groups.append(table["primary_key"])
    for columns in unique_groups:
        keys = [
            _hash([row[column] for column in columns])
            for row in samples
            if all(row.get(column) is not None for column in columns)
        ]
        if len(keys) != len(set(keys)):
            _issue(
                issues, "unique_sample", "实际生成的样例违反 UNIQUE 约束", table=table["name"], column=",".join(columns)
            )


def check_document(
    conn: Connection,
    document: dict[str, Any],
    schema_hash: str,
    *,
    count: int = 3,
    preview: bool = False,
    sample_max_attempts: int | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Validate against fresh DDL and real parent sources without inserting rows.

    Optional sample budgets apply independently to each table stream. Cancellation
    propagates the guard's original exception and never becomes a validation issue.
    """
    if cancel_check is not None:
        cancel_check()
    if not 1 <= count <= 100:
        raise WorkbenchError("预览 count 必须在 1–100 之间")
    if sample_max_attempts is not None and (type(sample_max_attempts) is not int or sample_max_attempts <= 0):
        raise WorkbenchError("sample_max_attempts 必须为正整数或 None")

    def guard() -> None:
        if cancel_check is not None:
            try:
                cancel_check()
            except Exception as exc:
                raise GenerationCancelledError(exc) from exc

    schema = inspect_connection(conn)
    issues: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "ok": False,
        "schema_hash": schema["schema_hash"],
        "config_hash": "",
        "issues": issues,
        "order": [],
        "layers": [],
        "samples": {},
        "effective_rules": {},
        "sources": [],
        "preview_complete": True,
    }
    if schema_hash != schema["schema_hash"]:
        _issue(issues, "schema_changed", "数据库结构已变化，请刷新 schema 后重新检查")
    try:
        config = bind_document(conn, document)
    except (WorkbenchError, TypeError, AttributeError) as exc:
        _issue(issues, getattr(exc, "code", "invalid_config"), public_error(exc))
        return result
    if config.provider.value == "mimesis":
        availability = package_availability("mimesis", "mimesis")
        if not availability["available"]:
            missing = availability["status"] == "not_installed"
            _issue(
                issues,
                "provider_not_installed" if missing else "provider_import_error",
                "当前配置使用 Mimesis，但尚未安装；请在插件页安装，或明确更改生成引擎后重新检查。"
                if missing
                else "当前配置使用 Mimesis，但组件加载异常；请在插件页查看修复指引，或明确更改生成引擎。",
                component_id="mimesis",
                recovery_action="install" if missing else "repair",
            )
            return result
    if not config.tables:
        _issue(issues, "empty_plan", "请至少选择一张需要生成的表")
    if len({table.name for table in config.tables}) != len(config.tables):
        _issue(issues, "duplicate_table", "同一计划不能重复配置同一张表")
    tables = {table["name"]: table for table in schema["tables"]}
    _column_issues(config, tables, issues)
    normalized = config.model_dump(mode="json", exclude={"db_path", "url"})
    try:
        with DataOrchestrator.from_config(config) as orch:
            guard()
            if orch._provider_name != config.provider.value:
                raise WorkbenchError(f"provider {config.provider.value} 不可用，不能使用降级 provider 代替")
            orch._registry.get(config.provider.value).set_locale(config.locale)
            order, layers, deferred, evidence = _dependency_plan(config, schema, orch, issues)
            result.update(order=order, layers=layers, preview_complete=not deferred, sources=evidence["source_checks"])
            result["config_hash"] = _hash(
                {"document": normalized, "schema_hash": schema["schema_hash"], "sources": evidence}
            )
            if not any(issue["severity"] == "error" for issue in issues):
                configs = {table.name: table for table in config.tables}
                for name in order:
                    guard()
                    table = configs[name]
                    try:
                        runtime_columns = _runtime_columns(config, table, orch)
                        specs, user_configs, unique, composite = orch._resolve_specs(
                            name, table.count, None, runtime_columns, table.enrich
                        )
                        guard()
                        result["effective_rules"][name] = {
                            key: {k: v for k, v in asdict(spec).items() if k != "params"}
                            | {"params": {k: v for k, v in spec.params.items() if not k.startswith("_")}}
                            for key, spec in specs.items()
                        }
                        stream = orch._build_stream(
                            specs,
                            user_configs,
                            unique,
                            None,
                            table.seed,
                            table_name=name,
                            composite_unique=composite,
                            max_attempts=sample_max_attempts,
                            cancel_check=cancel_check,
                        )
                        if name in deferred:
                            # Validate the independent part of a deferred table without
                            # inventing the database-generated keys it will later consume.
                            blocked = {column for fk in tables[name]["foreign_keys"] for column in fk["columns"]}
                            blocked.update(
                                association.column_name
                                for association in config.associations
                                if name in association.target_tables
                            )
                            for node in ColumnDAG().build(specs, runtime_columns):
                                if any(dependency in blocked for dependency in node.depends_on):
                                    blocked.add(node.name)
                            independent = {key: spec for key, spec in specs.items() if key not in blocked}
                            independent_users = {
                                key: value for key, value in user_configs.items() if key not in blocked
                            }
                            partial_stream = orch._build_stream(
                                independent,
                                independent_users,
                                unique - blocked,
                                None,
                                table.seed,
                                table_name=name,
                                composite_unique=[
                                    columns for columns in composite if not blocked.intersection(columns)
                                ],
                                max_attempts=sample_max_attempts,
                                cancel_check=cancel_check,
                            )
                            partial_samples = next(
                                partial_stream.generate(min(count, table.count), min(count, table.count)), []
                            )
                            _sample_issues(
                                tables[name], partial_samples, issues, dialect=schema["dialect"], excluded=blocked
                            )
                            continue
                        samples = next(stream.generate(min(count, table.count), min(count, table.count)), [])
                        _sample_issues(tables[name], samples, issues, dialect=schema["dialect"])
                        if preview:
                            result["samples"][name] = samples
                    except GenerationCancelledError:
                        raise
                    except GenerationBudgetExceededError as exc:
                        location = f"表 {name}"
                        if exc.column is not None:
                            location += f" 的列 {exc.column}（generator: {exc.generator}）"
                        _issue(
                            issues,
                            "generation_invalid",
                            f"样例校验在{location}达到 {exc.limit} 次尝试上限，请检查唯一值空间或约束冲突。",
                            table=name,
                            column=exc.column,
                            generator=exc.generator,
                            attempt_limit=exc.limit,
                        )
                    except Exception as exc:  # noqa: BLE001
                        # Generator/provider failures become sanitized, table-specific validation issues.
                        _issue(issues, "generation_invalid", public_error(exc), table=name)
    except GenerationCancelledError as exc:
        raise exc.reason from None
    except Exception as exc:  # noqa: BLE001
        # The validation boundary reports arbitrary adapter failures without SQL or credentials.
        _issue(issues, "validation_failed", public_error(exc))
    if cancel_check is not None:
        cancel_check()
    result["ok"] = not any(issue["severity"] == "error" for issue in issues)
    return result


def _checked_saved(
    conn: Connection, store: WorkspaceStore, draft_id: str, revision: int, schema_hash: str, config_hash: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    draft = store.get_draft(draft_id)
    if draft["revision"] != revision:
        raise WorkbenchError("草稿版本已变化，请重新保存并检查", code="revision_conflict", status=409)
    schema = inspect_connection(conn)
    if draft["target_key"] != schema["target_key"]:
        raise WorkbenchError("草稿与当前连接目标不匹配", code="target_mismatch", status=409)
    if draft["schema_hash"] != schema_hash:
        raise WorkbenchError("已保存草稿的 schema 版本不匹配", code="schema_changed", status=409)
    checked = check_document(conn, draft["document"], schema_hash)
    if not checked["ok"]:
        raise WorkbenchError(
            "检查未通过：" + "; ".join(i["message"] for i in checked["issues"] if i["severity"] == "error"),
            code="check_failed",
            status=409,
        )
    if not config_hash or checked["config_hash"] != config_hash:
        raise WorkbenchError("配置或数据来源已变化，请重新检查", code="check_stale", status=409)
    return draft, schema, checked


def _execution_options(execution: dict[str, Any] | None) -> dict[str, Any]:
    try:
        return normalize_execution(execution)
    except ValueError as exc:
        raise WorkbenchError(str(exc), code="invalid_execution") from exc


def _require_execution_plan(plan: dict[str, Any], plan_hash: str) -> None:
    if not plan["ok"]:
        raise WorkbenchError(
            "清空计划未通过：" + "; ".join(i["message"] for i in plan["issues"] if i["severity"] == "error"),
            code="execution_blocked",
            status=409,
        )
    if plan["mode"] == "replace_selected" and (not plan_hash or plan["plan_hash"] != plan_hash):
        raise WorkbenchError("清空计划已变化，请重新预检并确认", code="execution_plan_stale", status=409)


def plan_execution(
    conn_id: str,
    draft_id: str,
    revision: int,
    schema_hash: str,
    config_hash: str,
    *,
    execution: dict[str, Any] | None = None,
    registry: UIState = state,
    store: WorkspaceStore | None = None,
) -> dict[str, Any]:
    """Read a saved/check-bound execution plan without changing the target."""
    store = store or get_store()
    options = _execution_options(execution)
    with registry.connection_operation(conn_id) as conn:
        draft, schema, checked = _checked_saved(conn, store, draft_id, revision, schema_hash, config_hash)
        return build_execution_plan(
            conn, bind_document(conn, draft["document"]), schema, checked["order"], options, config_hash
        )


def start_run(
    conn_id: str,
    draft_id: str,
    revision: int,
    schema_hash: str,
    config_hash: str,
    *,
    execution: dict[str, Any] | None = None,
    plan_hash: str = "",
    registry: UIState = state,
    store: WorkspaceStore | None = None,
) -> dict[str, Any]:
    """Reserve a live connection and execute only an unchanged, saved, checked revision."""
    store = store or get_store()
    options = _execution_options(execution)
    with registry.connection_operation(conn_id, write=True) as conn:
        draft, schema, checked = _checked_saved(conn, store, draft_id, revision, schema_hash, config_hash)
        plan = build_execution_plan(
            conn, bind_document(conn, draft["document"]), schema, checked["order"], options, config_hash
        )
        _require_execution_plan(plan, plan_hash)
        tables_by_name = {table["name"]: table for table in draft["document"]["tables"]}
        payload = {
            "draft_id": draft_id,
            "revision": revision,
            "name": draft["name"],
            "target_key": draft["target_key"],
            "target_label": draft["target_label"],
            "document": draft["document"],
            "schema_hash": schema_hash,
            "config_hash": config_hash,
            "execution": options,
            "plan_hash": plan["plan_hash"],
            "status": "queued",
            "order": checked["order"],
            "rows_inserted": 0,
            "errors": [],
            "tables": [
                {
                    "name": name,
                    "status": "queued",
                    "requested_count": tables_by_name[name]["count"],
                    "rows_inserted": 0,
                    "errors": [],
                    "batch_count": 0,
                    "elapsed": 0.0,
                }
                for name in checked["order"]
            ],
        }
        job = registry.create_job(conn_id, "workbench", draft["name"])
        try:
            run = store.create_run(payload, require_current_draft=True)
        except Exception as exc:
            # Reserve before writing the immutable record: another session
            # targeting the same DB must not leave a duplicate queued record.
            registry.complete_job(job.job_id, error=public_error(exc))
            raise
    try:
        start_background(
            target=execute_run,
            args=(run["id"], conn_id, job.job_id),
            kwargs={"registry": registry, "store": store},
            daemon=True,
            name=f"sqlseed-run-{run['id']}",
            category="job",
        )
    except Exception as exc:
        try:
            store.update_run(run["id"], {"status": "error", "errors": [public_error(exc)], "finished_at": time.time()})
        except Exception:  # noqa: BLE001
            # A secondary persistence failure must still release the reserved job below.
            logger.error("Failed to persist workbench startup failure", run_id=run["id"])
        finally:
            registry.complete_job(job.job_id, error=public_error(exc))
        raise
    return run


def _execute_replacement(
    conn: Connection,
    run: dict[str, Any],
    store: WorkspaceStore,
    tables: list[dict[str, Any]],
    outcome: dict[str, Any],
) -> int:
    """Keep every delete, sequence reset, FK read and streamed batch in one transaction."""
    config = bind_document(conn, run["document"])
    configs = {table.name: table for table in config.tables}
    staged: dict[str, dict[str, Any]] = {}
    with DataOrchestrator.from_config(config) as orch:
        orch.get_table_names()
        adapter = orch.database_adapter
        if not isinstance(adapter, SQLAlchemyAdapter):
            raise WorkbenchError("清空生成需要 SQLAlchemyAdapter", code="execution_blocked")
        with adapter.transaction():
            outcome["rolled_back"] = True
            transaction_conn = replace(conn, orchestrator=orch)
            # BEGIN IMMEDIATE prevents another connection from changing the
            # target between this final read and the destructive statements.
            checked = check_document(transaction_conn, run["document"], run["schema_hash"])
            if not checked["ok"] or checked["config_hash"] != run["config_hash"]:
                raise WorkbenchError("执行前数据库来源或结构已变化，请重新检查与确认清空计划", code="check_stale")
            schema = inspect_connection(transaction_conn)
            plan = build_execution_plan(
                transaction_conn, config, schema, checked["order"], run["execution"], run["config_hash"]
            )
            _require_execution_plan(plan, run["plan_hash"])
            for name in plan["delete_order"]:
                adapter.execute(f"DELETE FROM {quote_identifier(name)}").close()
            if run["execution"]["reset_identity"]:
                # Do not use the legacy dialect reset helper, which suppresses
                # SQLite errors. A reset failure must roll back this whole run.
                for table in schema["tables"]:
                    if table["name"] in plan["delete_order"] and any(
                        column["is_autoincrement"] for column in table["columns"]
                    ):
                        adapter.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table["name"],)).close()
            orch._relation.clear_cache()
            orch._shared_pool.clear()
            for item in tables:
                table = configs[item["name"]]
                item["status"] = "running"
                store.update_run(run["id"], {"tables": tables})
                result = orch.fill_table(
                    table.name,
                    count=table.count,
                    batch_size=table.batch_size,
                    seed=table.seed,
                    column_configs=_runtime_columns(config, table, orch),
                    clear_before=False,
                    transform=None,
                    enrich=table.enrich,
                    skip_ai=True,
                )
                if result.errors:
                    raise WorkbenchError("; ".join(public_error(ValueError(error)) for error in result.errors))
                staged[table.name] = {
                    "rows_inserted": result.count,
                    "batch_count": result.batch_count,
                    "elapsed": result.elapsed,
                }
                violations = orch.query(f"PRAGMA foreign_key_check({quote_identifier(table.name)})")
                if violations:
                    raise WorkbenchError(f"{table.name} 生成后的外键检查未通过")
        # Only the successful context exit above makes staged counts committed.
        outcome.update(committed=True, rolled_back=False)
        for item in tables:
            item.update(status="done", **staged[item["name"]])
    return sum(item["rows_inserted"] for item in tables)


def execute_run(
    run_id: str, conn_id: str, job_id: str, *, registry: UIState = state, store: WorkspaceStore | None = None
) -> None:
    """Run a frozen plan under the connection lock; persist each completed table."""
    try:
        store = store or get_store()
        run = store.get_run(run_id)
    except Exception as exc:  # noqa: BLE001
        # Failed snapshot loading must finish the reserved job, including storage failures.
        error = public_error(exc)
        try:
            if store is not None:
                store.update_run(run_id, {"status": "error", "errors": [error], "finished_at": time.time()})
        except Exception:  # noqa: BLE001
            # Secondary storage failures must not prevent releasing the job in finally.
            logger.error("Workbench run snapshot unavailable", run_id=run_id)
        finally:
            registry.complete_job(job_id, error=error)
        return
    tables = run["tables"]
    errors: list[str] = []
    total = 0
    started = time.monotonic()
    replacing = run.get("execution", {}).get("mode") == "replace_selected"
    outcome: dict[str, Any] = {"atomic": replacing, "committed": False, "rolled_back": False}
    try:
        with registry.connection_operation(conn_id, job_id=job_id) as conn:
            checked = check_document(conn, run["document"], run["schema_hash"])
            if not checked["ok"] or checked["config_hash"] != run["config_hash"]:
                raise WorkbenchError("排队期间配置来源或 schema 已变化，运行未开始", code="check_stale")
            config = bind_document(conn, run["document"])
            store.update_run(run_id, {"status": "running", "started_at": time.time()})
            if replacing:
                total = _execute_replacement(conn, run, store, tables, outcome)
                return
            configs = {table.name: table for table in config.tables}
            with DataOrchestrator.from_config(config) as orch:
                for item in tables:
                    table = configs[item["name"]]
                    item["status"] = "running"
                    store.update_run(run_id, {"tables": tables})
                    result = orch.fill_table(
                        table.name,
                        count=table.count,
                        batch_size=table.batch_size,
                        seed=table.seed,
                        column_configs=_runtime_columns(config, table, orch),
                        clear_before=False,
                        transform=None,
                        enrich=table.enrich,
                        skip_ai=True,
                    )
                    total += result.count
                    item.update(
                        status="error" if result.errors else "done",
                        rows_inserted=result.count,
                        batch_count=result.batch_count,
                        elapsed=result.elapsed,
                        errors=[public_error(ValueError(error)) for error in result.errors],
                    )
                    store.update_run(run_id, {"tables": tables, "rows_inserted": total})
                    if result.errors:
                        errors.extend(item["errors"])
                        break
    except Exception as exc:  # noqa: BLE001
        # The worker boundary records sanitized failures while preserving committed counts.
        errors.append(public_error(exc))
        if replacing and outcome["committed"]:
            # Disposal/reporting failures after COMMIT cannot erase rows that
            # are already committed or claim the transaction rolled back.
            total = sum(item["rows_inserted"] for item in tables)
        for item in tables:
            if item["status"] == "running":
                item.update(status="error", rows_inserted=0 if replacing else None, errors=[public_error(exc)])
    finally:
        for item in tables:
            if item["status"] == "queued":
                item["status"] = "not_run"
        terminal = {
            "status": "error" if errors else "done",
            "tables": tables,
            "rows_inserted": total,
            "errors": errors,
            "elapsed": time.monotonic() - started,
            "finished_at": time.time(),
            "row_counts_exact": all(item["rows_inserted"] is not None for item in tables),
        }
        if replacing:
            terminal["result"] = outcome
        try:
            store.update_run(run_id, terminal)
        except Exception as exc:  # noqa: BLE001
            # Terminal persistence failures must still publish and release the in-memory job.
            persistence_error = f"无法保存运行终态：{public_error(exc)}"
            errors.append(persistence_error)
            terminal["status"] = "error"
            logger.error("Failed to persist workbench run", run_id=run_id, error=persistence_error)
            # A bounded second publication handles a record-validation failure.
            # If storage itself is unavailable, the interrupted-run recovery on
            # the next server start remains authoritative for the persisted run.
            try:
                store.update_run(run_id, {"status": "error", "error": persistence_error, "finished_at": time.time()})
            except Exception:  # noqa: BLE001
                # The bounded fallback must release the job even when storage remains unavailable.
                logger.error("Workbench run storage unavailable", run_id=run_id)
        finally:
            registry.complete_job(job_id, result=terminal, error="; ".join(errors) or None, rows_inserted=total)
