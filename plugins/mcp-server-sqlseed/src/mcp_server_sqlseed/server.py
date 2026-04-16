from __future__ import annotations

import hashlib
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sqlseed")


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
            {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column}
            for fk in ctx["foreign_keys"]
        ],
        "indexes": ctx["indexes"],
        "sample_data": ctx["sample_data"],
        "all_table_names": ctx["all_table_names"],
    }


def _compute_schema_hash(schema_ctx: dict[str, Any]) -> str:
    hash_input = json.dumps(
        {
            "columns": [
                {"name": c.name, "type": c.type, "nullable": c.nullable}
                for c in schema_ctx["columns"]
            ],
            "foreign_keys": [
                {"column": fk.column, "ref_table": fk.ref_table}
                for fk in schema_ctx["foreign_keys"]
            ],
        },
        sort_keys=True,
    )
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


@mcp.resource("sqlseed://schema/{db_path}/{table_name}")
def get_schema_resource(db_path: str, table_name: str) -> str:
    from sqlseed.core.orchestrator import DataOrchestrator

    with DataOrchestrator(db_path) as orch:
        ctx = orch.get_schema_context(table_name)
        serializable_ctx = _serialize_schema_context(ctx)
        return json.dumps(serializable_ctx, ensure_ascii=False, indent=2)


@mcp.tool()
def sqlseed_inspect_schema(db_path: str, table_name: str | None = None) -> dict[str, Any]:
    """Inspect database schema. Returns column info, foreign keys, indexes,
    sample data, and schema_hash for specified table or all tables."""
    from sqlseed.core.orchestrator import DataOrchestrator

    with DataOrchestrator(db_path) as orch:
        tables = [table_name] if table_name else orch._db.get_table_names()
        result: dict[str, Any] = {}
        for tbl in tables:
            ctx = orch.get_schema_context(tbl)
            result[tbl] = _serialize_schema_context(ctx)
            result[tbl]["schema_hash"] = _compute_schema_hash(ctx)
        return result


@mcp.tool()
def sqlseed_generate_yaml(db_path: str, table_name: str, max_retries: int = 3) -> str:
    """Generate YAML config for a table using AI analysis with self-correction.
    Returns YAML string for human review. Requires sqlseed-ai plugin and API key."""
    import yaml
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.refiner import AiConfigRefiner, AISuggestionFailedError

    analyzer = SchemaAnalyzer()
    refiner = AiConfigRefiner(analyzer, db_path)

    try:
        result = refiner.generate_and_refine(
            table_name=table_name,
            max_retries=max_retries,
        )
    except AISuggestionFailedError as e:
        return f"# AI suggestion failed: {e}"
    except Exception as e:
        return f"# Error: {e}"

    if result:
        output = {"db_path": db_path, "provider": "mimesis", "locale": "zh_CN", "tables": [result]}
        return yaml.dump(output, allow_unicode=True, sort_keys=False, default_flow_style=False)
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
    from sqlseed.core.orchestrator import DataOrchestrator

    with DataOrchestrator(db_path) as orch:
        column_configs = None
        clear_before = False
        seed = None

        if yaml_config:
            import yaml as _yaml

            from sqlseed.config.models import GeneratorConfig

            data = _yaml.safe_load(yaml_config)
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
