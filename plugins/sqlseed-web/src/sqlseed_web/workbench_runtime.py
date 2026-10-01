"""Offline plan validation and server-owned multi-table execution for the workbench."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.engine import make_url
from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import quote_identifier
from sqlseed._utils.type_checks import has_exact_type
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
from sqlseed.core.result import GenerationResult
from sqlseed.core.stream import GenerationBudgetExceededError, GenerationCancelledError
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from sqlseed.generators._dispatch import GeneratorDispatchMixin

from sqlseed_web._diagnostic_text import CREDENTIAL_KEY_PATTERN
from sqlseed_web.diagnostics import public_error as _public_error
from sqlseed_web.messages import message as tr
from sqlseed_web.messages import message_list
from sqlseed_web.operation_errors import generation_errors
from sqlseed_web.runtime_lifecycle import start_background
from sqlseed_web.settings_environment import package_availability
from sqlseed_web.state import Connection, UIState, state
from sqlseed_web.workbench_cycles import (
    ExistingSourceOrchestrator,
    existing_cycle_sources,
)
from sqlseed_web.workbench_cycles import (
    cyclic_components as _cyclic_components,
)
from sqlseed_web.workbench_cycles import (
    dependency_layers as _layers,
)
from sqlseed_web.workbench_cycles import read_source_values as _source_values
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


def public_error(exc: Exception) -> str:
    """Keep the existing runtime import available for Web API callers."""
    return _public_error(exc)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _identity(target: str) -> str:
    if "://" not in target:
        return str(Path(target).expanduser().resolve())
    url = make_url(target)
    database = url.database
    if url.get_backend_name() == "sqlite" and database and database != ":memory:":
        return str(Path(database).expanduser().resolve())
    secret_keys = [key for key in url.query if re.search(CREDENTIAL_KEY_PATTERN, key, re.IGNORECASE)]
    return url._replace(password=None).difference_update_query(secret_keys).render_as_string(hide_password=False)


def _reject_extra(value: Any, fields: Any, path: str) -> None:
    if isinstance(value, dict) and (extra := set(value) - set(fields)):
        raise WorkbenchError(
            tr("backend.workbench_runtime.contains_unknown_fields", p1=path, p2=", ".join(sorted(extra))),
            code="unknown_field",
        )


def _validate_table_keys(table: Any) -> None:
    _reject_extra(table, TableConfig.model_fields, "table")
    if not isinstance(table, dict):
        return
    for column in table.get("columns", []) or []:
        if isinstance(column, dict):
            _reject_extra(column.get("constraints"), ColumnConstraintsConfig.model_fields, "constraints")


def _validate_keys(raw: dict[str, Any]) -> None:
    _reject_extra(raw, GeneratorConfig.model_fields, tr("backend.workbench_runtime.configuration"))
    for table in raw.get("tables", []) or []:
        _validate_table_keys(table)
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
        raise WorkbenchError(tr("backend.workbench_runtime.provide_only_one_of_db_path_and"), code="target_mismatch")
    for supplied in (db_path, url):
        if supplied is not None and _identity(str(supplied)) != _identity(conn.target):
            raise WorkbenchError(
                tr("backend.workbench_runtime.the_configuration_target_does_not_match_the"),
                code="target_mismatch",
                status=409,
            )
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
        raise WorkbenchError(
            tr("backend.workbench_runtime.cannot_parse_yaml_json", p1=public_error(exc)), code="parse_error"
        ) from exc
    if not isinstance(raw, dict):
        raise WorkbenchError(
            tr("backend.workbench_runtime.configuration_must_be_a_yaml_json_object"), code="parse_error"
        )
    return normalize_document(conn, raw)


def export_document(conn: Connection, document: dict[str, Any]) -> dict[str, Any]:
    """Export an executable core config, with URL passwords and secret query options removed."""
    config = bind_document(conn, document).model_dump(mode="json", exclude_none=True)
    omitted = False
    if config.get("url"):
        url = make_url(config["url"])
        secret_keys = [key for key in url.query if re.search(CREDENTIAL_KEY_PATTERN, key, re.IGNORECASE)]
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


def _can_omit(column: dict[str, Any]) -> bool:
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
    if (mappings := config.custom_column_mappings) is None:
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


def _table_option_issues(table: TableConfig, issues: list[dict[str, Any]]) -> None:
    if table.clear_before:
        _issue(
            issues,
            "clear_not_supported",
            tr("backend.workbench_runtime.the_workbench_does_not_support_this_fk"),
            table=table.name,
        )
    if table.transform:
        _issue(
            issues,
            "transform_not_supported",
            tr("backend.workbench_runtime.the_workbench_does_not_execute_server_side"),
            table=table.name,
        )


def _unique_domain_issues(
    column: ColumnConfig,
    table: TableConfig,
    metadata: dict[str, Any],
    context: dict[str, str],
    issues: list[dict[str, Any]],
) -> None:
    single_unique = [constraint["columns"] for constraint in metadata["unique_constraints"]]
    single_unique.append(metadata["primary_key"])
    is_unique = [column.name] in single_unique or bool(column.constraints and column.constraints.unique)
    if is_unique and column.null_ratio == 0:
        choices = column.params.get("choices", column.params.get("weighted_choices"))
        if (
            column.generator in {"choice", "weighted_choice"}
            and isinstance(choices, (list, dict))
            and (available := len({_hash(value) for value in choices})) < table.count
        ):
            _issue(
                issues,
                "unique_domain_exhausted",
                tr(
                    "backend.workbench_runtime.only_explicit_candidate_values_are_available_insufficient",
                    p1=available,
                    p2=table.count,
                ),
                **context,
            )
        minimum, maximum = column.params.get("min_value"), column.params.get("max_value")
        if (
            column.generator == "integer"
            and isinstance(minimum, int)
            and isinstance(maximum, int)
            and maximum - minimum + 1 < table.count
        ):
            _issue(
                issues,
                "unique_domain_exhausted",
                tr("backend.workbench_runtime.the_explicit_integer_range_is_too_small"),
                **context,
            )


def _derived_column_issues(
    column: ColumnConfig, columns: dict[str, Any], context: dict[str, str], issues: list[dict[str, Any]]
) -> None:
    sources = column.derive_from
    for source in [sources] if isinstance(sources, str) else sources or []:
        if source not in columns:
            _issue(
                issues,
                "unknown_derive_source",
                tr("backend.workbench_runtime.the_derived_source_column_does_not_exist", p1=source),
                **context,
            )
    if column.expression:
        try:
            expression = ast.parse(column.expression, mode="eval")
            allowed_calls = set(ExpressionEngine.SAFE_FUNCTIONS) | {"lookup"}
            for call in ast.walk(expression):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id not in allowed_calls:
                    _issue(
                        issues,
                        "unknown_expression_function",
                        tr("backend.workbench_runtime.unsupported_expression_function", p1=call.func.id),
                        **context,
                    )
        except SyntaxError as exc:
            _issue(issues, "invalid_expression", public_error(exc), **context)


def _column_presence_issues(
    column: ColumnConfig, info: dict[str, Any], context: dict[str, str], issues: list[dict[str, Any]]
) -> None:
    if column.null_ratio > 0 and not info.get("nullable", True):
        _issue(issues, "not_null", tr("backend.workbench_runtime.not_null_columns_cannot_have_null_ratio"), **context)
    can_skip = _can_omit(info)
    if column.generator == "skip" and not info.get("nullable", True) and not can_skip:
        _issue(
            issues, "required_column", tr("backend.workbench_runtime.a_not_null_column_without_a_default"), **context
        )


def _table_column_issues(
    config: GeneratorConfig, table: TableConfig, metadata: dict[str, Any], known: set[str], issues: list[dict[str, Any]]
) -> None:
    _table_option_issues(table, issues)
    columns = {column["name"]: column for column in metadata["columns"]}
    seen: set[str] = set()
    for column in table.columns:
        context = {"table": table.name, "column": column.name}
        if column.name in seen:
            _issue(
                issues, "duplicate_column", tr("backend.workbench_runtime.duplicate_column_configuration"), **context
            )
        seen.add(column.name)
        if column.provider is not None and column.provider != config.provider:
            _issue(
                issues,
                "column_provider_not_supported",
                tr("backend.workbench_runtime.core_uses_a_global_provider_different_per"),
                **context,
            )
        if column.generator and column.generator not in known:
            _issue(
                issues,
                "unknown_generator",
                tr("backend.workbench_runtime.unknown_generator", p1=column.generator),
                **context,
            )
        if (info := columns.get(column.name)) is None:
            _issue(
                issues,
                "unknown_column",
                tr("backend.workbench_runtime.the_column_no_longer_exists_refresh_the"),
                **context,
            )
            continue
        _unique_domain_issues(column, table, metadata, context, issues)
        _column_presence_issues(column, info, context, issues)
        _derived_column_issues(column, columns, context, issues)


def _column_issues(config: GeneratorConfig, tables: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    known = set(GeneratorDispatchMixin.GENERATOR_MAP) | {"skip", "foreign_key", "foreign_key_or_integer"}
    for table in config.tables:
        if table.name not in tables:
            _issue(issues, "unknown_table", tr("backend.workbench_runtime.the_table_does_not_exist"), table=table.name)
            continue
        _table_column_issues(config, table, tables[table.name], known, issues)
    if config.snapshot_dir:
        _issue(
            issues,
            "snapshot_not_supported",
            tr("backend.workbench_runtime.the_workbench_uses_persistent_run_records_and"),
        )
    if config.custom_column_mappings:
        mappings = config.custom_column_mappings
        for generator in (
            *[rule.generator for rule in mappings.exact.values()],
            *[rule.generator for rule in mappings.pattern],
        ):
            if generator not in known:
                _issue(
                    issues,
                    "unknown_generator",
                    tr("backend.workbench_runtime.custom_mappings_contain_an_unknown_generator", p1=generator),
                )
        for rule in mappings.pattern:
            try:
                re.compile(rule.pattern)
            except re.error as exc:
                _issue(issues, "invalid_pattern", public_error(exc))


def _empty_source_issues(
    context: dict[str, Any],
    columns: list[str],
    nullable: bool,
    selected: set[str],
    deferred: set[str],
    issues: list[dict[str, Any]],
) -> None:
    parent, target = context["source_table"], context["table"]
    if parent == target:
        if not nullable:
            _issue(
                issues,
                "self_reference_no_seed",
                tr("backend.workbench_runtime.an_empty_table_with_a_not_null"),
                **context,
            )
        elif len(columns) > 1:
            _issue(
                issues,
                "composite_self_reference",
                tr("backend.workbench_runtime.core_does_not_guarantee_second_phase_backfill"),
                **context,
            )
        else:
            _issue(
                issues,
                "self_reference_backfill",
                tr("backend.workbench_runtime.nullable_self_references_first_generate_null_then"),
                severity="warning",
                **context,
            )
    elif parent in selected:
        deferred.add(target)
        _issue(
            issues,
            "preview_requires_parent",
            tr("backend.workbench_runtime.the_parent_table_has_no_available_values"),
            severity="warning",
            **context,
        )
    elif nullable:
        _issue(
            issues,
            "nullable_parent_empty",
            tr("backend.workbench_runtime.empty_parent_nullable_reference"),
            severity="warning",
            **context,
        )
    else:
        _issue(
            issues,
            "missing_parent_source",
            tr("backend.workbench_runtime.a_non_nullable_foreign_key_or_association"),
            **context,
        )


def _association_sources(
    config: GeneratorConfig,
    tables: dict[str, Any],
    dependencies: dict[str, set[str]],
    source: Callable[[str, str, list[str], bool, list[str]], None],
    issues: list[dict[str, Any]],
) -> None:
    for association in config.associations:
        if association.strategy != "shared_pool":
            _issue(
                issues,
                "association_strategy",
                tr("backend.workbench_runtime.core_does_not_currently_distinguish_the_random"),
            )
        for name in association.target_tables:
            if name not in tables or association.column_name not in {c["name"] for c in tables[name]["columns"]}:
                _issue(
                    issues,
                    "invalid_association_target",
                    tr("backend.workbench_runtime.the_association_target_table_or_column_does"),
                    table=name,
                    column=association.column_name,
                )
            elif name in dependencies:
                source(
                    name,
                    association.source_table,
                    [association.source_column or association.column_name],
                    False,
                    [association.column_name],
                )


def _foreign_key_sources(
    tables: dict[str, Any],
    dependencies: dict[str, set[str]],
    source: Callable[[str, str, list[str], bool, list[str]], None],
    issues: list[dict[str, Any]],
) -> None:
    for name in dependencies:
        for fk in tables[name]["foreign_keys"]:
            if fk.get("ref_schema") not in (None, "", "public", "main"):
                _issue(
                    issues,
                    "cross_schema_fk",
                    tr("backend.workbench_runtime.core_does_not_guarantee_generation_of_cross"),
                    table=name,
                )
                continue
            if len(fk["columns"]) > 2:
                _issue(
                    issues,
                    "composite_fk_width",
                    tr("backend.workbench_runtime.core_does_not_guarantee_tuple_pairing_for"),
                    table=name,
                )
                continue
            source(name, fk["ref_table"], fk["ref_columns"], fk["nullable"], fk["columns"])


def _dependency_plan(
    config: GeneratorConfig, schema: dict[str, Any], orch: DataOrchestrator, issues: list[dict[str, Any]]
) -> tuple[list[str], list[list[str]], set[str], dict[str, Any]]:
    tables = {table["name"]: table for table in schema["tables"]}
    selected = {table.name for table in config.tables}
    dependencies = {table.name: set[str]() for table in config.tables if table.name in tables}
    references: list[dict[str, Any]] = []
    deferred: set[str] = set()
    evidence: dict[str, Any] = {
        "row_counts": {name: table["row_count"] for name, table in tables.items()},
        "source_checks": [],
    }

    def source(target: str, parent: str, columns: list[str], nullable: bool, target_columns: list[str]) -> None:
        context = {
            "table": target,
            "column": ",".join(target_columns),
            "source_table": parent,
        }
        if parent not in tables or any(name not in {c["name"] for c in tables[parent]["columns"]} for name in columns):
            _issue(
                issues,
                "invalid_parent_source",
                tr("backend.workbench_runtime.the_referenced_source_table_or_column_does"),
                columns=target_columns,
                **context,
            )
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
            references.append(
                {
                    "table": target,
                    "columns": target_columns,
                    "source_table": parent,
                    "source_columns": columns,
                }
            )
        if not values:
            _empty_source_issues({**context, "columns": target_columns}, columns, nullable, selected, deferred, issues)

    _foreign_key_sources(tables, dependencies, source, issues)
    _association_sources(config, tables, dependencies, source, issues)
    components = _cyclic_components(dependencies)
    pinned = existing_cycle_sources(config, schema, evidence["source_checks"], components)
    evidence["existing_cycle_sources"] = pinned
    for source_info in pinned:
        dependencies[source_info["table"]].discard(source_info["source_table"])
    order, layers = _layers(dependencies)
    if len(order) != len(dependencies):
        components = _cyclic_components(dependencies)
        members = set().union(*components)
        _issue(
            issues,
            "cross_table_cycle",
            tr("backend.workbench_runtime.cross_table_cycles_require_general_backfill_the"),
            tables=[name for name in dependencies if name in members],
            references=[
                reference
                for reference in references
                if any(reference["table"] in group and reference["source_table"] in group for group in components)
            ],
            edge_ids=[
                edge["id"]
                for edge in schema["edges"]
                if edge["source"] != edge["target"]
                and any(edge["source"] in group and edge["target"] in group for group in components)
            ],
        )
    return order, layers, deferred, evidence


def _sample_issues(
    table: dict[str, Any],
    samples: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    *,
    excluded: set[str] | None = None,
) -> None:
    excluded = excluded or set()
    for column in table["columns"]:
        name = column["name"]
        if name in excluded or column.get("nullable", True):
            continue
        can_skip = _can_omit(column)
        if any(row.get(name) is None and (name in row or not can_skip) for row in samples):
            _issue(
                issues,
                "not_null_sample",
                tr("backend.workbench_runtime.an_actual_generated_sample_violates_not_null"),
                table=table["name"],
                column=name,
            )
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
                issues,
                "unique_sample",
                tr("backend.workbench_runtime.an_actual_generated_sample_violates_unique"),
                table=table["name"],
                column=",".join(columns),
            )


@dataclass(frozen=True)
class _PreviewOptions:
    count: int
    preview: bool
    sample_max_attempts: int | None
    cancel_check: Callable[[], None] | None

    def guard(self) -> None:
        if self.cancel_check is not None:
            try:
                self.cancel_check()
            except Exception as exc:
                raise GenerationCancelledError(exc) from exc


@dataclass(frozen=True)
class _SampleRules:
    columns: list[ColumnConfig]
    specs: dict[str, Any]
    user_configs: dict[str, Any]
    unique: set[str]
    composite: list[list[str]]


def _resolve_sample_rules(config: GeneratorConfig, table: TableConfig, orch: DataOrchestrator) -> _SampleRules:
    columns = _runtime_columns(config, table, orch)
    specs, user_configs, unique, composite = orch._resolve_specs(table.name, table.count, None, columns, table.enrich)
    return _SampleRules(columns, specs, user_configs, unique, composite)


def _preview_provider_available(config: GeneratorConfig, issues: list[dict[str, Any]]) -> bool:
    if config.provider.value == "mimesis":
        availability = package_availability("mimesis", "mimesis")
        if not availability["available"]:
            missing = availability["status"] == "not_installed"
            _issue(
                issues,
                "provider_not_installed" if missing else "provider_import_error",
                tr("backend.workbench_runtime.this_configuration_uses_mimesis_which_is_not")
                if missing
                else tr("backend.workbench_runtime.this_configuration_uses_mimesis_which_failed_to"),
                component_id="mimesis",
                recovery_action="install" if missing else "repair",
            )
            return False
    return True


def _deferred_table_samples(
    config: GeneratorConfig,
    table: TableConfig,
    metadata: dict[str, Any],
    orch: DataOrchestrator,
    rules: _SampleRules,
    options: _PreviewOptions,
    issues: list[dict[str, Any]],
) -> None:
    # Validate the independent part of a deferred table without
    # inventing the database-generated keys it will later consume.
    blocked = {column for fk in metadata["foreign_keys"] for column in fk["columns"]}
    blocked.update(
        association.column_name for association in config.associations if table.name in association.target_tables
    )
    for node in ColumnDAG().build(rules.specs, rules.columns):
        if any(dependency in blocked for dependency in node.depends_on):
            blocked.add(node.name)
    independent = {key: spec for key, spec in rules.specs.items() if key not in blocked}
    independent_users = {key: value for key, value in rules.user_configs.items() if key not in blocked}
    partial_stream = orch._build_stream(
        independent,
        independent_users,
        rules.unique - blocked,
        None,
        table.seed,
        table_name=table.name,
        composite_unique=[columns for columns in rules.composite if not blocked.intersection(columns)],
        max_attempts=options.sample_max_attempts,
        cancel_check=options.cancel_check,
    )
    partial_samples = next(
        partial_stream.generate(min(options.count, table.count), min(options.count, table.count)), []
    )
    _sample_issues(metadata, partial_samples, issues, excluded=blocked)


def _table_samples(
    config: GeneratorConfig,
    table: TableConfig,
    tables: dict[str, Any],
    orch: DataOrchestrator,
    result: dict[str, Any],
    options: _PreviewOptions,
    deferred: bool,
) -> None:
    issues = result["issues"]
    name = table.name
    rules = _resolve_sample_rules(config, table, orch)
    options.guard()
    result["effective_rules"][name] = {
        key: {k: v for k, v in asdict(spec).items() if k != "params"}
        | {"params": {k: v for k, v in spec.params.items() if not k.startswith("_")}}
        for key, spec in rules.specs.items()
    }
    stream = orch._build_stream(
        rules.specs,
        rules.user_configs,
        rules.unique,
        None,
        table.seed,
        table_name=name,
        composite_unique=rules.composite,
        max_attempts=options.sample_max_attempts,
        cancel_check=options.cancel_check,
    )
    if deferred:
        _deferred_table_samples(config, table, tables[name], orch, rules, options, issues)
        return
    samples = next(stream.generate(min(options.count, table.count), min(options.count, table.count)), [])
    _sample_issues(tables[name], samples, issues)
    if options.preview:
        result["samples"][name] = samples


def _preview_tables(
    config: GeneratorConfig,
    tables: dict[str, Any],
    order: list[str],
    deferred: set[str],
    orch: DataOrchestrator,
    result: dict[str, Any],
    options: _PreviewOptions,
) -> None:
    issues = result["issues"]
    configs = {table.name: table for table in config.tables}
    for name in order:
        options.guard()
        table = configs[name]
        try:
            _table_samples(config, table, tables, orch, result, options, name in deferred)
        except GenerationCancelledError:
            raise
        except GenerationBudgetExceededError as exc:
            location = tr("backend.workbench_runtime.table", p1=name)
            if exc.column is not None:
                location = message_list(
                    [location, tr("backend.workbench_runtime.column_generator", p1=exc.column, p2=exc.generator)], ""
                )
            _issue(
                issues,
                "generation_invalid",
                tr(
                    "backend.workbench_runtime.sample_validation_reached_its_limit_of_attempts",
                    p1=location,
                    p2=exc.limit,
                ),
                table=name,
                column=exc.column,
                generator=exc.generator,
                attempt_limit=exc.limit,
            )
        except generation_errors(orch) as exc:
            _issue(issues, "generation_invalid", public_error(exc), table=name)


def _check_generation(
    config: GeneratorConfig, schema: dict[str, Any], result: dict[str, Any], options: _PreviewOptions
) -> None:
    issues = result["issues"]
    if not config.tables:
        _issue(issues, "empty_plan", tr("backend.workbench_runtime.select_at_least_one_table_to_generate"))
    if len({table.name for table in config.tables}) != len(config.tables):
        _issue(issues, "duplicate_table", tr("backend.workbench_runtime.a_table_cannot_occur_more_than_once"))
    tables = {table["name"]: table for table in schema["tables"]}
    _column_issues(config, tables, issues)
    normalized = config.model_dump(mode="json", exclude={"db_path", "url"})
    orch: DataOrchestrator | None = None
    try:
        with ExistingSourceOrchestrator.for_config(config) as orch:
            options.guard()
            if orch._provider_name != config.provider.value:
                raise WorkbenchError(
                    tr(
                        "backend.workbench_runtime.provider_is_unavailable_a_fallback_provider_cannot",
                        p1=config.provider.value,
                    )
                )
            orch._registry.get(config.provider.value).set_locale(config.locale)
            order, layers, deferred, evidence = _dependency_plan(config, schema, orch, issues)
            pinned = evidence["existing_cycle_sources"]
            orch.pin_cycle_sources(pinned)
            result.update(
                order=order,
                layers=layers,
                preview_complete=not deferred,
                sources=evidence["source_checks"],
                existing_cycle_sources=pinned,
            )
            result["config_hash"] = _hash(
                {"document": normalized, "schema_hash": schema["schema_hash"], "sources": evidence}
            )
            if not any(issue["severity"] == "error" for issue in issues):
                _preview_tables(config, tables, order, deferred, orch, result, options)
    except GenerationCancelledError as exc:
        raise exc.reason from None
    except generation_errors(orch) as exc:
        _issue(issues, "validation_failed", public_error(exc))


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
        raise WorkbenchError(tr("backend.workbench_runtime.preview_count_must_be_between_1_and"))
    if sample_max_attempts is not None and (not has_exact_type(sample_max_attempts, int) or sample_max_attempts <= 0):
        raise WorkbenchError(tr("backend.workbench_runtime.sample_max_attempts_must_be_a_positive"))

    options = _PreviewOptions(count, preview, sample_max_attempts, cancel_check)

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
        _issue(issues, "schema_changed", tr("backend.workbench_runtime.the_database_schema_has_changed_refresh_it"))
    try:
        config = bind_document(conn, document)
    except (WorkbenchError, TypeError, AttributeError) as exc:
        _issue(issues, getattr(exc, "code", "invalid_config"), public_error(exc))
        return result
    if not _preview_provider_available(config, issues):
        return result
    _check_generation(config, schema, result, options)
    if cancel_check is not None:
        cancel_check()
    result["ok"] = not any(issue["severity"] == "error" for issue in issues)
    return result


def _checked_saved(
    conn: Connection, store: WorkspaceStore, draft_id: str, revision: int, schema_hash: str, config_hash: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    draft = store.get_draft(draft_id)
    if draft["revision"] != revision:
        raise WorkbenchError(
            tr("backend.workbench_runtime.the_draft_revision_has_changed_save_and"),
            code="revision_conflict",
            status=409,
        )
    schema = inspect_connection(conn)
    if draft["target_key"] != schema["target_key"]:
        raise WorkbenchError(
            tr("backend.workbench_runtime.the_draft_does_not_match_the_current"), code="target_mismatch", status=409
        )
    if draft["schema_hash"] != schema_hash:
        raise WorkbenchError(
            tr("backend.workbench_runtime.the_saved_draft_s_schema_version_does"), code="schema_changed", status=409
        )
    checked = check_document(conn, draft["document"], schema_hash)
    if not checked["ok"]:
        raise WorkbenchError(
            message_list(
                [
                    tr("backend.workbench_runtime.checks_failed"),
                    message_list(i["message"] for i in checked["issues"] if i["severity"] == "error"),
                ],
                "",
            ),
            code="check_failed",
            status=409,
        )
    if not config_hash or checked["config_hash"] != config_hash:
        raise WorkbenchError(
            tr("backend.workbench_runtime.the_configuration_or_data_sources_have_changed"),
            code="check_stale",
            status=409,
        )
    return draft, schema, checked


def _execution_options(execution: dict[str, Any] | None) -> dict[str, Any]:
    try:
        return normalize_execution(execution)
    except ValueError as exc:
        raise WorkbenchError(public_error(exc), code="invalid_execution") from exc


def _require_execution_plan(plan: dict[str, Any], plan_hash: str) -> None:
    if not plan["ok"]:
        raise WorkbenchError(
            message_list(
                [
                    tr("backend.workbench_runtime.clear_plan_checks_failed"),
                    message_list(i["message"] for i in plan["issues"] if i["severity"] == "error"),
                ],
                "",
            ),
            code="execution_blocked",
            status=409,
        )
    if plan["mode"] == "replace_selected" and (not plan_hash or plan["plan_hash"] != plan_hash):
        raise WorkbenchError(
            tr("backend.workbench_runtime.the_clear_plan_has_changed_review_and"),
            code="execution_plan_stale",
            status=409,
        )


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
            conn,
            bind_document(conn, draft["document"]),
            schema,
            checked["order"],
            options,
            config_hash,
            atomic_append=bool(checked.get("existing_cycle_sources")),
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
            conn,
            bind_document(conn, draft["document"]),
            schema,
            checked["order"],
            options,
            config_hash,
            atomic_append=bool(checked.get("existing_cycle_sources")),
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
            "atomic_append": options["mode"] == "append" and plan["atomic"],
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
        except (KeyError, ValueError, RuntimeError, OSError, sqlite3.Error):
            logger.error("Failed to persist workbench startup failure", run_id=run["id"])
        finally:
            registry.complete_job(job.job_id, error=public_error(exc))
        raise
    return run


def _fill_run_table(config: GeneratorConfig, table: TableConfig, orch: DataOrchestrator) -> GenerationResult:
    return orch.fill_table(
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


def _replacement_plan(
    conn: Connection, config: GeneratorConfig, run: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    # BEGIN IMMEDIATE prevents another connection from changing the
    # target between this final read and the destructive statements.
    checked = check_document(conn, run["document"], run["schema_hash"])
    if not checked["ok"] or checked["config_hash"] != run["config_hash"]:
        raise WorkbenchError(
            tr("backend.workbench_runtime.database_sources_or_schema_changed_before_execution"), code="check_stale"
        )
    schema = inspect_connection(conn)
    plan = build_execution_plan(conn, config, schema, checked["order"], run["execution"], run["config_hash"])
    _require_execution_plan(plan, run["plan_hash"])
    return schema, plan


def _clear_replacement_tables(
    adapter: SQLAlchemyAdapter, plan: dict[str, Any], schema: dict[str, Any], reset_identity: bool
) -> None:
    for name in plan["delete_order"]:
        adapter.execute(f"DELETE FROM {quote_identifier(name)}").close()
    if reset_identity:
        # Do not use the legacy dialect reset helper, which suppresses
        # SQLite errors. A reset failure must roll back this whole run.
        for table in schema["tables"]:
            if table["name"] in plan["delete_order"] and any(column["is_autoincrement"] for column in table["columns"]):
                adapter.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table["name"],)).close()


def _fill_replacement_tables(
    orch: DataOrchestrator,
    config: GeneratorConfig,
    run: dict[str, Any],
    store: WorkspaceStore,
    tables: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    configs = {table.name: table for table in config.tables}
    staged: dict[str, dict[str, Any]] = {}
    for item in tables:
        table = configs[item["name"]]
        item["status"] = "running"
        store.update_run(run["id"], {"tables": tables})
        result = _fill_run_table(config, table, orch)
        if result.errors:
            raise WorkbenchError(message_list(public_error(ValueError(error)) for error in result.errors))
        staged[table.name] = {
            "rows_inserted": result.count,
            "batch_count": result.batch_count,
            "elapsed": result.elapsed,
        }
        if orch.query(f"PRAGMA foreign_key_check({quote_identifier(table.name)})"):
            raise WorkbenchError(
                tr("backend.workbench_runtime.foreign_key_checks_failed_after_generating", p1=table.name)
            )
    return staged


def _execute_atomic_run(
    conn: Connection,
    run: dict[str, Any],
    store: WorkspaceStore,
    tables: list[dict[str, Any]],
    outcome: dict[str, Any],
    *,
    replacing: bool,
) -> int:
    """Keep sources, optional deletes and streamed inserts in one SQLite transaction."""
    config = bind_document(conn, run["document"])
    with ExistingSourceOrchestrator.for_config(config) as orch:
        orch.get_table_names()
        adapter = orch.database_adapter
        if not isinstance(adapter, SQLAlchemyAdapter):
            raise WorkbenchError(tr("backend.workbench_runtime.cycle_source_rules_not_supported"))
        with adapter.transaction():
            outcome["rolled_back"] = True
            orch._preflight_generation([table.name for table in config.tables])
            active = Connection(
                conn_id=conn.conn_id,
                target=conn.target,
                provider=conn.provider,
                locale=conn.locale,
                orchestrator=orch,
            )
            if replacing:
                schema, plan = _replacement_plan(active, config, run)
                _clear_replacement_tables(adapter, plan, schema, run["execution"]["reset_identity"])
                orch._relation.clear_cache()
                orch._shared_pool.clear()
            else:
                checked = _current_run_check(active, run)
                orch.pin_cycle_sources(checked["existing_cycle_sources"])
            staged = _fill_replacement_tables(orch, config, run, store, tables)
        # A successful context exit is the first point that counts are committed.
        outcome.update(committed=True, rolled_back=False)
        for item in tables:
            item.update(status="done", **staged[item["name"]])
    return sum(item["rows_inserted"] for item in tables)


def _run_snapshot_failure(
    run_id: str, job_id: str, store: WorkspaceStore | None, registry: UIState, exc: Exception
) -> None:
    # Failed snapshot loading must finish the reserved job, including storage failures.
    error = public_error(exc)
    try:
        if store is not None:
            store.update_run(run_id, {"status": "error", "errors": [error], "finished_at": time.time()})
    except (KeyError, ValueError, RuntimeError, OSError, sqlite3.Error):
        logger.error("Workbench run snapshot unavailable", run_id=run_id)
    finally:
        registry.complete_job(job_id, error=error)


@dataclass
class _RunProgress:
    rows_inserted: int
    errors: list[str]


def _current_run_check(conn: Connection, run: dict[str, Any]) -> dict[str, Any]:
    checked = check_document(conn, run["document"], run["schema_hash"])
    if not checked["ok"] or checked["config_hash"] != run["config_hash"]:
        raise WorkbenchError(
            tr("backend.workbench_runtime.configuration_sources_or_schema_changed_while_queued"), code="check_stale"
        )
    return checked


def _append_run_tables(
    config: GeneratorConfig, run_id: str, store: WorkspaceStore, tables: list[dict[str, Any]], progress: _RunProgress
) -> None:
    configs = {table.name: table for table in config.tables}
    with DataOrchestrator.from_config(config) as orch:
        for item in tables:
            table = configs[item["name"]]
            item["status"] = "running"
            store.update_run(run_id, {"tables": tables})
            result = _fill_run_table(config, table, orch)
            progress.rows_inserted += result.count
            item.update(
                status="error" if result.errors else "done",
                rows_inserted=result.count,
                batch_count=result.batch_count,
                elapsed=result.elapsed,
                errors=[public_error(ValueError(error)) for error in result.errors],
            )
            store.update_run(run_id, {"tables": tables, "rows_inserted": progress.rows_inserted})
            if result.errors:
                progress.errors.extend(item["errors"])
                break


def _run_execution_failure(
    exc: Exception, tables: list[dict[str, Any]], progress: _RunProgress, outcome: dict[str, Any], replacing: bool
) -> None:
    # The worker boundary records sanitized failures while preserving committed counts.
    progress.errors.append(public_error(exc))
    if replacing and outcome["committed"]:
        # Disposal/reporting failures after COMMIT cannot erase rows that
        # are already committed or claim the transaction rolled back.
        progress.rows_inserted = sum(item["rows_inserted"] for item in tables)
    for item in tables:
        if item["status"] == "running":
            item.update(status="error", rows_inserted=0 if replacing else None, errors=[public_error(exc)])


def _run_terminal(
    tables: list[dict[str, Any]], progress: _RunProgress, started: float, outcome: dict[str, Any], replacing: bool
) -> dict[str, Any]:
    for item in tables:
        if item["status"] == "queued":
            item["status"] = "not_run"
    terminal: dict[str, Any] = {
        "status": "error" if progress.errors else "done",
        "tables": tables,
        "rows_inserted": progress.rows_inserted,
        "errors": progress.errors,
        "elapsed": time.monotonic() - started,
        "finished_at": time.time(),
        "row_counts_exact": all(item["rows_inserted"] is not None for item in tables),
    }
    if replacing:
        terminal["result"] = outcome
    return terminal


def _publish_run_terminal(
    run_id: str,
    job_id: str,
    registry: UIState,
    store: WorkspaceStore,
    terminal: dict[str, Any],
    progress: _RunProgress,
) -> None:
    persisted = False
    persistence_error = tr("backend.workbench_runtime.saving_the_final_run_state_was_interrupted")
    try:
        store.update_run(run_id, terminal)
        persisted = True
    except (KeyError, ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        persistence_error = tr("backend.workbench_runtime.cannot_save_the_final_run_state", p1=public_error(exc))
    finally:
        try:
            if not persisted:
                progress.errors.append(persistence_error)
                terminal["status"] = "error"
                logger.error("Failed to persist workbench run", run_id=run_id, error=persistence_error)
                _persist_failed_terminal(store, run_id, persistence_error)
        finally:
            registry.complete_job(
                job_id,
                result=terminal,
                error=message_list(progress.errors) or None,
                rows_inserted=progress.rows_inserted,
            )


def _persist_failed_terminal(store: WorkspaceStore, run_id: str, error: str) -> None:
    """Try one minimal error record; the next startup recovers unavailable storage."""
    try:
        store.update_run(run_id, {"status": "error", "error": error, "errors": [error], "finished_at": time.time()})
    except (KeyError, ValueError, RuntimeError, OSError, sqlite3.Error):
        logger.error("Workbench run storage unavailable", run_id=run_id)


def execute_run(
    run_id: str, conn_id: str, job_id: str, *, registry: UIState = state, store: WorkspaceStore | None = None
) -> None:
    """Run a frozen plan under the connection lock; persist each completed table."""
    with registry.job_completion(job_id):
        run = None
        try:
            store = store or get_store()
            run = store.get_run(run_id)
        except (KeyError, ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            _run_snapshot_failure(run_id, job_id, store, registry, exc)
            return
        finally:
            if run is None and registry.job_snapshot(job_id).status == "running":
                _run_snapshot_failure(
                    run_id,
                    job_id,
                    store,
                    registry,
                    RuntimeError(tr("backend.workbench_runtime.reading_the_run_snapshot_was_interrupted_unexpectedly")),
                )
        _execute_loaded_run(run, conn_id, job_id, registry, store)


def _execute_loaded_run(
    run: dict[str, Any], conn_id: str, job_id: str, registry: UIState, store: WorkspaceStore
) -> None:
    run_id = run["id"]
    tables = run["tables"]
    progress = _RunProgress(rows_inserted=0, errors=[])
    started = time.monotonic()
    replacing = run.get("execution", {}).get("mode") == "replace_selected"
    atomic = replacing or bool(run.get("atomic_append"))
    outcome: dict[str, Any] = {"atomic": atomic, "committed": False, "rolled_back": False}
    conn: Connection | None = None
    finished = False
    try:
        with registry.connection_operation(conn_id, job_id=job_id) as conn:
            _current_run_check(conn, run)
            config = bind_document(conn, run["document"])
            store.update_run(run_id, {"status": "running", "started_at": time.time()})
            if atomic:
                progress.rows_inserted = _execute_atomic_run(conn, run, store, tables, outcome, replacing=replacing)
            else:
                _append_run_tables(config, run_id, store, tables, progress)
        finished = True
    except generation_errors(conn.orchestrator if conn is not None else None, additional=(KeyError,)) as exc:
        _run_execution_failure(exc, tables, progress, outcome, atomic)
        finished = True
    finally:
        if not finished:
            _run_execution_failure(
                RuntimeError(tr("backend.workbench_runtime.the_run_stopped_unexpectedly_check_the_service")),
                tables,
                progress,
                outcome,
                atomic,
            )
        _publish_run_terminal(
            run_id, job_id, registry, store, _run_terminal(tables, progress, started, outcome, atomic), progress
        )
