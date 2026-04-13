from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sqlseed")


@mcp.tool()
def sqlseed_inspect_schema(db_path: str, table_name: str | None = None) -> dict[str, Any]:
    """Inspect database schema. Returns column info, foreign keys, indexes, and sample data for specified table or all tables."""
    from sqlseed.core.orchestrator import DataOrchestrator

    with DataOrchestrator(db_path) as orch:
        tables = [table_name] if table_name else orch._db.get_table_names()
        result: dict[str, Any] = {}
        for tbl in tables:
            columns = orch._schema.get_column_info(tbl)
            fks = orch._db.get_foreign_keys(tbl)
            indexes = orch._schema.get_index_info(tbl)
            sample = orch._schema.get_sample_data(tbl, limit=3)
            result[tbl] = {
                "columns": [
                    {
                        "name": c.name,
                        "type": c.type,
                        "nullable": c.nullable,
                        "default": c.default,
                        "is_primary_key": c.is_primary_key,
                        "is_autoincrement": c.is_autoincrement,
                    }
                    for c in columns
                ],
                "foreign_keys": [
                    {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column}
                    for fk in fks
                ],
                "indexes": [
                    {"name": idx.name, "columns": idx.columns, "unique": idx.unique}
                    for idx in indexes
                ],
                "sample_data": sample,
            }
        return result


@mcp.tool()
def sqlseed_generate_yaml(db_path: str, table_name: str) -> str:
    """Generate YAML configuration suggestions for a table using AI analysis. Returns YAML string for human review. Requires sqlseed-ai plugin and API key."""
    import yaml

    from sqlseed.core.orchestrator import DataOrchestrator

    with DataOrchestrator(db_path) as orch:
        columns = orch._schema.get_column_info(table_name)
        fks = orch._db.get_foreign_keys(table_name)
        all_tables = orch._db.get_table_names()
        indexes = orch._schema.get_index_info(table_name)
        sample_data = orch._schema.get_sample_data(table_name, limit=5)

        result = orch._plugins.hook.sqlseed_ai_analyze_table(
            table_name=table_name,
            columns=columns,
            indexes=[{"name": i.name, "columns": i.columns, "unique": i.unique} for i in indexes],
            sample_data=sample_data,
            foreign_keys=fks,
            all_table_names=all_tables,
        )

        if result:
            output = {"db_path": db_path, "provider": "mimesis", "locale": "zh_CN", "tables": [result]}
            return yaml.dump(output, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return "# No AI suggestions available. Ensure sqlseed-ai plugin is installed and API key is configured."


@mcp.tool()
def sqlseed_execute_fill(db_path: str, table_name: str, count: int = 1000, yaml_config: str | None = None) -> dict[str, Any]:
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
        )

        return {
            "table_name": result.table_name,
            "count": result.count,
            "elapsed": result.elapsed,
            "errors": result.errors,
        }
