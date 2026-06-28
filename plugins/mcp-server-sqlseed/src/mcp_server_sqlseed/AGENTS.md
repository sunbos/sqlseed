<!-- Parent: ../../AGENTS.md -->
**Generated:** 2026-06-21

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

| URI Pattern | Handler | Return Type | Description |
|-------------|---------|-------------|-------------|
| `sqlseed://schema/{db_path}/{table_name}` | `get_schema_resource` | `str` (JSON) | Get schema info for a single table |

### Tools

| Tool Name | Parameters | Return Type | Description |
|-----------|------------|-------------|-------------|
| `sqlseed_inspect_schema` | `db_path: str`, `table_name: str | None = None` | `dict[str, Any]` | Inspect database schema (includes schema_hash) |
| `sqlseed_generate_yaml` | `db_path: str`, `table_name: str`, `max_retries: int = 3`, `api_key: str | None = None`, `base_url: str | None = None`, `model: str | None = None` | `str` (YAML or error text) | AI-generate YAML config |
| `sqlseed_execute_fill` | `db_path: str`, `table_name: str`, `count: int = 1000`, `yaml_config: str | None = None`, `enrich: bool = False` | `dict[str, Any]` | Execute data filling |
| `sqlseed_gemma4_analyze` | `db_path: str`, `table_name: str`, `model: str | None = None`, `backend: str | None = None` | `dict[str, Any]` | Gemma 4 analyzes table structure and recommends config |
| `sqlseed_gemma4_agent_fill` | `db_path: str`, `table_name: str`, `count: int = 1000`, `model: str | None = None`, `backend: str | None = None`, `max_retries: int = 3` | `dict[str, Any]` | Gemma 4 end-to-end: analyze → generate → fill |
| `sqlseed_list_gemma_models` | (no parameters) | `dict[str, Any]` | List Gemma 4 model variants and backends |

- `_validate_db_target()` validates that the extension must be `.db`, `.sqlite`, or `.sqlite3`
- `_MAX_YAML_CONFIG_SIZE = 256 * 1024` (256KB) limits the YAML config size
- `MCPServerConfig` defines `host`/`port` fields, used by `FastMCP()` initialization in `server.py` via `config.host`/`config.port`
- MCP's `_compute_schema_hash()` uses the first 16 characters of SHA256, same as the AI plugin's `_compute_schema_hash()` — they are separate functions in different modules but use the same truncation length

## For AI Agents

### Working In This Directory

- Adding a new MCP tool requires registering it in `server.py` with `@mcp.tool()`
- All user input must pass through validation functions (`_validate_db_target` validates path extension and existence, `_validate_table_name` validates that the table exists in the database)
- YAML config has a size limit (`_MAX_YAML_CONFIG_SIZE`) to prevent oversized input
- AI features are gated by the `_AI_AVAILABLE` flag; when unavailable, it degrades to non-AI mode
- The server layer should stay thin; delegate business logic to `sqlseed.core.orchestrator` and `sqlseed_ai`

### Testing Requirements

```bash
pip install -e "./plugins/mcp-server-sqlseed"
pytest
```

### Common Patterns

- MCP tool definition: `@mcp.tool()` decorator registers the tool; parameters are auto-inferred from the function signature
- Input validation: `_validate_db_target()` + `_validate_table_name()` double validation
- AI fallback: `try: from sqlseed_ai import ... except ImportError: _AI_AVAILABLE = False`

## Dependencies

### Internal

- `sqlseed` (core.orchestrator, config.loader, config.models)
- `sqlseed_ai` (optional, SchemaAnalyzer, AiConfigRefiner)

### External

- `mcp>=1.0,<2` — MCP server framework

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
