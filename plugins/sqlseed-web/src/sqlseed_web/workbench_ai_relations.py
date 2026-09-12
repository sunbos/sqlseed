"""Finite AI relation templates compiled by the server, never by the model."""

from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from sqlseed._utils.type_checks import has_exact_type
from sqlseed.config.models import ColumnConfig
from sqlseed.core.check_parser import CheckConstraintParser, ParsedCheck
from sqlseed.core.column_dag import ColumnDAG
from sqlseed.core.mapper import GeneratorSpec


class RelationSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["relation"]
    table: str = Field(min_length=1, max_length=300)
    column: str = Field(min_length=1, max_length=300)
    template: Literal["copy", "concat", "product", "date_offset"]
    sources: list[str] = Field(min_length=1, max_length=8)
    options: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="请确认同一行字段之间的业务关系。", max_length=2000)


def locked_column(
    table: dict[str, Any], column: dict[str, Any], rule: dict[str, Any] | None, *, source: bool = False
) -> bool:
    """Protect managed rules; skipped values cannot supply a relation source."""
    foreign = {name for key in table["foreign_keys"] for name in key["columns"]}
    protected: tuple[str, ...] = ("faker_method", "mimesis_method", "native_params")
    if not source:
        protected += ("derive_from", "expression")
    generator = (rule or {}).get("generator") or table.get("mapping", {}).get(column["name"], {}).get("generator_name")
    # An existing derived rule supplies a value even if the SQL column also
    # declares DEFAULT. It may feed another relation but remains a locked target.
    derived = bool(rule and rule.get("derive_from") and rule.get("expression"))
    uses_default = (
        not derived
        and column.get("default") is not None
        and (not generator or generator == "skip" or str(generator).startswith("__"))
    )
    return bool(
        column["name"] in foreign
        or column.get("is_primary_key")
        or column.get("is_computed")
        or uses_default
        or (rule and (any(rule.get(key) for key in protected) or (source and rule.get("generator") == "skip")))
    )


def _kind(column: dict[str, Any]) -> str:
    name = str(column["type"]).upper()
    if "INT" in name:
        return "integer"
    if any(token in name for token in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL")):
        return "number"
    if "DATETIME" in name or "TIMESTAMP" in name:
        return "datetime"
    if name == "DATE":
        return "date"
    if any(token in name for token in ("TEXT", "CHAR", "STRING")):
        return "text"
    return name


def _copy_expression(kinds: list[str], target_kind: str, options: dict[str, Any]) -> str:
    if (
        options
        or len(kinds) != 1
        or not (kinds[0] == target_kind or (kinds[0] == "integer" and target_kind == "number"))
    ):
        raise ValueError("复制需要兼容的单个来源")
    return "value"


def _concat_expression(kinds: list[str], target_kind: str, options: dict[str, Any], values: list[str]) -> str:
    separator = options.get("separator", "")
    if (
        set(options) - {"separator"}
        or not isinstance(separator, str)
        or len(separator) > 32
        or target_kind != "text"
        or any(kind != "text" for kind in kinds)
    ):
        raise ValueError("拼接仅支持文本字段与不超过 32 字的分隔符")
    return (" + " + json.dumps(separator, ensure_ascii=False) + " + ").join(values)


def _product_expression(kinds: list[str], target_kind: str, options: dict[str, Any], values: list[str]) -> str:
    precision = options.get("precision", 2 if target_kind == "number" else 0)
    if set(options) - {"precision"} or not has_exact_type(precision, int) or not 0 <= precision <= 8:
        raise ValueError("乘积需要两个数值字段，精度为 0–8")
    if (
        len(kinds) != 2
        or any(kind not in {"integer", "number"} for kind in kinds)
        or target_kind not in {"integer", "number"}
    ):
        raise ValueError("乘积需要两个数值字段，精度为 0–8")
    if target_kind == "integer" and (precision != 0 or any(kind != "integer" for kind in kinds)):
        raise ValueError("整数目标需要整数来源")
    return f"round({values[0]} * {values[1]}, {precision})"


def _date_offset_expression(kinds: list[str], target_kind: str, options: dict[str, Any]) -> str:
    days = options.get("days", 0)
    if set(options) - {"days"} or not has_exact_type(days, int) or not -36500 <= days <= 36500:
        raise ValueError("日期偏移需要相同日期类型，天数为 -36500–36500")
    if len(kinds) != 1 or target_kind not in {"date", "datetime"} or kinds[0] != target_kind:
        raise ValueError("日期偏移需要相同日期类型，天数为 -36500–36500")
    return f"value + timedelta(days={days})"


def _relation_expression(suggestion: RelationSuggestion, kinds: list[str], target_kind: str, values: list[str]) -> str:
    if suggestion.template == "copy":
        return _copy_expression(kinds, target_kind, suggestion.options)
    if suggestion.template == "concat":
        return _concat_expression(kinds, target_kind, suggestion.options, values)
    if suggestion.template == "product":
        return _product_expression(kinds, target_kind, suggestion.options, values)
    return _date_offset_expression(kinds, target_kind, suggestion.options)


def compile_relation(
    suggestion: RelationSuggestion, table: dict[str, Any], rules: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Compile only bounded typed templates, with explicit NULL propagation."""
    columns = {col["name"]: col for col in table["columns"]}
    target = columns[suggestion.column]
    sources = [columns[name] for name in suggestion.sources]
    if len(set(suggestion.sources)) != len(sources) or suggestion.column in suggestion.sources:
        raise ValueError("来源不能重复或引用自身")
    if any(locked_column(table, col, rules.get(col["name"]), source=True) for col in sources):
        raise ValueError("来源必须是同一行中可生成的普通或派生字段")
    if not target.get("nullable", True) and any(
        col.get("nullable", True) or (rules.get(col["name"], {}).get("null_ratio") or 0) > 0 for col in sources
    ):
        raise ValueError("可空来源不能派生为不可空目标")
    kinds, target_kind = [_kind(col) for col in sources], _kind(target)
    values = ["value"] if len(sources) == 1 else [f"value[{index}]" for index in range(len(sources))]
    expression = _relation_expression(suggestion, kinds, target_kind, values)
    if suggestion.template != "copy":
        expression = f"None if {' or '.join(value + ' == None' for value in values)} else ({expression})"
    after = deepcopy(rules.get(suggestion.column, {}))
    for key in ("generator", "params", "provider", "faker_method", "mimesis_method", "native_params"):
        after.pop(key, None)
    after.update(
        name=suggestion.column,
        derive_from=suggestion.sources[0] if len(sources) == 1 else suggestion.sources,
        expression=expression,
    )
    ColumnConfig.model_validate(after)
    return after


def validate_dags(document: dict[str, Any], schema: dict[str, Any]) -> None:
    """Use the real core DAG, retaining all old derived rules and row references."""
    tables = {table["name"]: table for table in schema["tables"]}
    for table in document["tables"]:
        columns = {col["name"] for col in tables[table["name"]]["columns"]}
        configs = [ColumnConfig.model_validate(col) for col in table.get("columns", [])]
        for config in configs:
            sources = (
                config.derive_from
                if isinstance(config.derive_from, list)
                else [config.derive_from]
                if config.derive_from
                else []
            )
            if not set(sources) <= columns:
                raise ValueError("派生来源不存在")
        ColumnDAG().build({name: GeneratorSpec(generator_name="string") for name in columns}, configs)


def _constraint_columns(table: dict[str, Any]) -> list[list[str]]:
    constraints = [constraint["columns"] for constraint in table["unique_constraints"]]
    for check in table["checks"]:
        try:
            columns = [column.name for column in parse_one(check["expression"]).find_all(exp.Column)]
        except SqlglotError:
            # If a dialect-specific constraint cannot be understood, keep
            # the table's proposals together rather than guessing independence.
            columns = [column["name"] for column in table["columns"]]
        constraints.append(columns)
    return constraints


def _patch_dependencies(
    document: dict[str, Any], schema: dict[str, Any]
) -> Iterator[tuple[tuple[str, str], tuple[str, str]]]:
    for table in document["tables"]:
        configs = [ColumnConfig.model_validate(col) for col in table.get("columns", [])]
        specs = {col.name: GeneratorSpec(generator_name="string") for col in configs}
        for node in ColumnDAG().build(specs, configs):
            for source in node.depends_on:
                yield (table["name"], source), (table["name"], node.name)
    for table in schema["tables"]:
        for columns in _constraint_columns(table):
            for name in columns[1:]:
                yield (table["name"], name), (table["name"], columns[0])


def group_patches(patches: list[dict[str, Any]], document: dict[str, Any], schema: dict[str, Any]) -> None:
    """Connected old/new derivations are a single review and application unit."""
    parents: dict[tuple[str, str], tuple[str, str]] = {}

    def root(node: tuple[str, str]) -> tuple[str, str]:
        parents.setdefault(node, node)
        if parents[node] != node:
            parents[node] = root(parents[node])
        return parents[node]

    for source, target in _patch_dependencies(document, schema):
        parents[root(source)] = root(target)
    groups: dict[tuple[str, str], str] = {}
    for patch in patches:
        group_root = root((patch["table"], patch["column"]))
        patch["group_id"] = groups.setdefault(group_root, f"ai-group-{len(groups) + 1}")


class SampleCheckError(ValueError):
    """Expose the failed schema constraint, never the generated value."""

    def __init__(self, table: str, column: str, message: str) -> None:
        super().__init__(f"{table}.{column}: {message}")
        self.issue = {
            "code": "sample_check_failed",
            "severity": "error",
            "table": table,
            "column": column,
            "message": message,
        }


def _validate_sample_value(table: str, column: str, parsed: ParsedCheck, value: Any) -> None:
    if value is None:
        return  # SQL CHECK accepts UNKNOWN; NOT NULL is checked separately.
    if parsed.kind == "choice" and value not in parsed.choices:
        raise SampleCheckError(table, column, "生成值不满足 CHECK 候选范围")
    if parsed.kind == "range":
        if parsed.min_value is not None and (
            value < parsed.min_value or (parsed.min_exclusive and value == parsed.min_value)
        ):
            raise SampleCheckError(
                table,
                column,
                f"生成值不满足 CHECK 下界（{'>' if parsed.min_exclusive else '>='} {parsed.min_value}）",
            )
        if parsed.max_value is not None and (
            value > parsed.max_value or (parsed.max_exclusive and value == parsed.max_value)
        ):
            raise SampleCheckError(
                table,
                column,
                f"生成值不满足 CHECK 上界（{'<' if parsed.max_exclusive else '<='} {parsed.max_value}）",
            )
    if parsed.kind == "length_range" and (
        (parsed.min_length is not None and len(value) < parsed.min_length)
        or (parsed.max_length is not None and len(value) > parsed.max_length)
    ):
        raise SampleCheckError(
            table,
            column,
            f"生成值长度不满足 CHECK（最少 {parsed.min_length if parsed.min_length is not None else 0}，"
            f"最多 {parsed.max_length if parsed.max_length is not None else '不限'}）",
        )


def validate_sample_checks(schema: dict[str, Any], samples: dict[str, Any]) -> None:
    """Check finite single-column constraints against actual generated values."""
    for table in schema["tables"]:
        for column in table["columns"]:
            for check in table["checks"]:
                if (parsed := CheckConstraintParser.parse(column["name"], check["expression"])) is None:
                    continue
                for row in samples.get(table["name"], []):
                    _validate_sample_value(table["name"], column["name"], parsed, row.get(column["name"]))
