<!-- Parent: ../../AGENTS.md -->
**Last updated:** 2026-07-12

# mcp_server_sqlseed

## Purpose

FastMCP server implementation. Provides AI assistants with sqlseed's data generation tools.

## Key Files

| File | Description |
|------|-------------|
| `server.py` | MCP tool definitions (`@mcp.tool()` decorators), core business logic |
| `config.py` | `MCPServerConfig` server configuration (db_path, host, port) |
| `__main__.py` | Server startup entry point |
| `__init__.py` | Package entry, exports `main` function |

## MCP Interface Contract

### Resources

None.

### Tools

| Tool Name | Parameters | Return Type | Description |
|-----------|------------|-------------|-------------|
| `sqlseed_generate_yaml` | `db_path: str`, `table_name: str` | `str` (YAML or error text) | Rule-driven YAML config template via core `ColumnMapper` (no LLM) |
| `sqlseed_execute_fill` | `db_path: str`, `table_name: str`, `count: int = 1000`, `yaml_config: str | None = None`, `enrich: bool = False` | `dict[str, Any]` | Execute data filling |

- `_validate_db_target()` validates that the extension must be `.db`, `.sqlite`, or `.sqlite3`
- `_MAX_YAML_CONFIG_SIZE = 256 * 1024` (256KB) limits the YAML config size
- `MCPServerConfig` defines `host`/`port` fields, used by `FastMCP()` initialization in `server.py` via `config.host`/`config.port`

## For AI Agents

### Working In This Directory

- Adding a new MCP tool requires registering it in `server.py` with `@mcp.tool()`
- All user input must pass through validation functions (`_validate_db_target` validates path extension and existence, `_validate_table_name` validates that the table exists in the database)
- YAML config has a size limit (`_MAX_YAML_CONFIG_SIZE`) to prevent oversized input
- The server layer should stay thin; delegate business logic to `sqlseed.core.orchestrator`

### Testing Requirements

```bash
pip install -e "./plugins/mcp-server-sqlseed"
pytest
```

### Common Patterns

- MCP tool definition: `@mcp.tool()` decorator registers the tool; parameters are auto-inferred from the function signature
- Input validation: `_validate_db_target()` + `_validate_table_name()` double validation

## Dependencies

### Internal

- `sqlseed` (core.orchestrator, config.loader, config.models)

### External

- `mcp>=1.0,<2` — MCP server framework

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
