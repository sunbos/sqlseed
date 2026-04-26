from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP

from sqlseed.config.models import GeneratorConfig
from sqlseed.core.orchestrator import DataOrchestrator

try:
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIConfig
    from sqlseed_ai.refiner import AiConfigRefiner, AISuggestionFailedError

    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False

mcp = FastMCP("sqlseed")

_MAX_YAML_CONFIG_SIZE = 256 * 1024


def _validate_db_path(db_path: str) -> str:
    resolved = Path(db_path).resolve()
    valid_exts = (".db", ".sqlite", ".sqlite3")
    if not str(resolved).endswith(valid_exts):
        raise ValueError(f"Invalid database path: {db_path}. Must be a .db, .sqlite, or .sqlite3 file.")
    if not resolved.exists():
        raise ValueError(f"Database file not found: {db_path}")
    return str(resolved)


def _validate_table_name(table_name: str, allowed_tables: list[str]) -> str:
    if table_name not in allowed_tables:
        raise ValueError(f"Table '{table_name}' does not exist in the database. Available: {allowed_tables}")
    return table_name


def _serialize_schema_context(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_name": ctx["table_name"],
        "columns": [
            {
                "name": c.name,
                "type": c.type,
                "nullable": c.nullable,
                "default": c.default,
                "is_primary_key": c.is_primary_key,
                "is_autoincrement": c.is_autoincrement,
            }
            for c in ctx["columns"]
        ],
        "foreign_keys": [
            {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column} for fk in ctx["foreign_keys"]
        ],
        "indexes": ctx["indexes"],
        "sample_data": ctx["sample_data"],
        "all_table_names": ctx["all_table_names"],
    }


def _compute_schema_hash(schema_ctx: dict[str, Any]) -> str:
    hash_input = json.dumps(
        {
            "columns": [{"name": c.name, "type": c.type, "nullable": c.nullable} for c in schema_ctx["columns"]],
            "foreign_keys": [{"column": fk.column, "ref_table": fk.ref_table} for fk in schema_ctx["foreign_keys"]],
        },
        sort_keys=True,
    )
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


@mcp.resource("sqlseed://schema/{db_path}/{table_name}")
def get_schema_resource(db_path: str, table_name: str) -> str:
    db_path = _validate_db_path(db_path)
    with DataOrchestrator(db_path) as orch:
        _validate_table_name(table_name, orch.get_table_names())
        ctx = orch.get_schema_context(table_name)
        serializable_ctx = _serialize_schema_context(ctx)
        return json.dumps(serializable_ctx, ensure_ascii=False, indent=2)


@mcp.tool()
def sqlseed_inspect_schema(db_path: str, table_name: str | None = None) -> dict[str, Any]:
    """Inspect database schema. Returns column info, foreign keys, indexes,
    sample data, and schema_hash for specified table or all tables."""
    db_path = _validate_db_path(db_path)
    with DataOrchestrator(db_path) as orch:
        if table_name:
            _validate_table_name(table_name, orch.get_table_names())
        tables = [table_name] if table_name else orch.get_table_names()
        result: dict[str, Any] = {}
        for tbl in tables:
            ctx = orch.get_schema_context(tbl)
            result[tbl] = _serialize_schema_context(ctx)
            result[tbl]["schema_hash"] = _compute_schema_hash(ctx)
        return result


@mcp.tool()
def sqlseed_generate_yaml(
    db_path: str,
    table_name: str,
    max_retries: int = 3,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> str:
    """Generate YAML config for a table using AI analysis with self-correction.
    Returns YAML string for human review. Requires sqlseed-ai plugin and API key."""
    if not _AI_AVAILABLE:
        return "# No AI suggestions available. Ensure sqlseed-ai plugin is installed and API key is configured."

    db_path = _validate_db_path(db_path)
    with DataOrchestrator(db_path) as orch:
        _validate_table_name(table_name, orch.get_table_names())

    ai_config = AIConfig.from_env().apply_overrides(api_key=api_key, base_url=base_url, model=model)

    ai_config.resolve_model()

    analyzer = SchemaAnalyzer(config=ai_config)
    refiner = AiConfigRefiner(analyzer, db_path)

    try:
        result = refiner.generate_and_refine(
            table_name=table_name,
            max_retries=max_retries,
        )
    except AISuggestionFailedError as e:
        return f"# AI suggestion failed: {e}"
    except (ValueError, RuntimeError, OSError) as e:
        return f"# Error: {e}"

    if result:
        output = {"db_path": db_path, "provider": "mimesis", "locale": "en_US", "tables": [result]}
        return str(yaml.dump(output, allow_unicode=True, sort_keys=False, default_flow_style=False))
    return "# No AI suggestions available. Ensure sqlseed-ai plugin is installed and API key is configured."


@mcp.tool()
def sqlseed_execute_fill(
    db_path: str,
    table_name: str,
    count: int = 1000,
    yaml_config: str | None = None,
    enrich: bool = False,
) -> dict[str, Any]:
    """Execute data generation for a table. Optionally provide YAML config string for column rules."""
    db_path = _validate_db_path(db_path)

    if yaml_config is not None and len(yaml_config) > _MAX_YAML_CONFIG_SIZE:
        raise ValueError(f"yaml_config exceeds maximum allowed size of {_MAX_YAML_CONFIG_SIZE} bytes")

    with DataOrchestrator(db_path) as orch:
        _validate_table_name(table_name, orch.get_table_names())
        column_configs = None
        clear_before = False
        seed = None

        if yaml_config:
            data = yaml.safe_load(yaml_config)
            config = GeneratorConfig(**data)
            for t in config.tables:
                if t.name == table_name:
                    column_configs = t.columns
                    clear_before = t.clear_before
                    seed = t.seed
                    break

        result = orch.fill_table(
            table_name=table_name,
            count=count,
            column_configs=column_configs,
            clear_before=clear_before,
            seed=seed,
            enrich=enrich,
        )

        return {
            "table_name": result.table_name,
            "count": result.count,
            "elapsed": result.elapsed,
            "errors": result.errors,
        }
