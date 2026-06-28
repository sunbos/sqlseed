"""MCP server exposing sqlseed core capabilities as tools.

Per ARCHITECTURE.md Section 3.4, this server exposes **core capabilities
only** (rule-driven YAML template generation + execute fill). It does NOT
depend on any LLM. Schema inspection and AI-driven analysis live in
``sqlseed-ai[mcp]`` (a separate MCP server) or in third-party MCPs such
as mcp-database-server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml
from mcp.server.fastmcp import FastMCP
from mcp_server_sqlseed.config import MCPServerConfig

from sqlseed._utils.logger import get_logger
from sqlseed._utils.paths import validate_db_target as _validate_db_target
from sqlseed._utils.paths import validate_table_name as _validate_table_name
from sqlseed.config.models import GeneratorConfig
from sqlseed.core.orchestrator import DataOrchestrator

logger = get_logger(__name__)

if TYPE_CHECKING:
    from sqlseed.core.mapper import GeneratorSpec

_server_config = MCPServerConfig()
mcp = FastMCP("sqlseed", host=_server_config.host, port=_server_config.port)

_MAX_YAML_CONFIG_SIZE = 256 * 1024


def _spec_to_column_entry(col_name: str, spec: GeneratorSpec) -> dict[str, Any]:
    """Convert a rule-driven GeneratorSpec into a YAML column config entry."""
    entry: dict[str, Any] = {"name": col_name, "generator": spec.generator_name}
    if spec.params:
        entry["params"] = dict(spec.params)
    if spec.null_ratio > 0:
        entry["null_ratio"] = spec.null_ratio
    return entry


@mcp.tool()
def sqlseed_generate_yaml(db_path: str, table_name: str) -> str:
    """Generate a YAML config template for a table using rule-driven column mapping.

    Uses sqlseed's core ``ColumnMapper`` (74 exact rules + 27 regex patterns)
    to infer a generator for each column. Offline, deterministic, no LLM
    required. For LLM-driven semantic inference, use the
    ``sqlseed_ai_generate_yaml`` tool from the ``sqlseed-ai[mcp]`` package.

    Returns a YAML string ready for human review and ``sqlseed_execute_fill``.
    """
    try:
        db_path = _validate_db_target(db_path)
        with DataOrchestrator(db_path) as orch:
            _validate_table_name(table_name, orch.get_table_names())
            specs = orch.get_column_mapping(table_name)

        columns = [_spec_to_column_entry(name, spec) for name, spec in specs.items()]
        output = {
            "db_path": db_path,
            "provider": "faker",
            "locale": "en_US",
            "tables": [{"name": table_name, "count": 1000, "columns": columns}],
        }
        logger.info("Rule-driven YAML generated", table_name=table_name, columns=len(columns))
        return str(yaml.dump(output, allow_unicode=True, sort_keys=False, default_flow_style=False))
    except (ValueError, RuntimeError, OSError) as e:
        logger.error("Failed to generate YAML", db_path=db_path, table_name=table_name, error=str(e))
        return f"# Error: {e}"


@mcp.tool()
def sqlseed_execute_fill(
    db_path: str,
    table_name: str,
    count: int = 1000,
    yaml_config: str | None = None,
    enrich: bool = False,
) -> dict[str, Any]:
    """Execute data generation for a table. Optionally provide YAML config string for column rules."""
    try:
        db_path = _validate_db_target(db_path)

        if yaml_config is not None and len(yaml_config.encode("utf-8")) > _MAX_YAML_CONFIG_SIZE:
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

            logger.info(
                "Fill completed",
                table_name=result.table_name,
                count=result.count,
                elapsed=result.elapsed,
            )
            return {
                "table_name": result.table_name,
                "count": result.count,
                "elapsed": result.elapsed,
                "errors": result.errors,
            }
    except (ValueError, RuntimeError, OSError) as e:
        logger.error("Failed to execute fill", db_path=db_path, table_name=table_name, error=str(e))
        return {"error": str(e)}
