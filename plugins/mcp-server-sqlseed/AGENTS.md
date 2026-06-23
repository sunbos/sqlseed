# MCP-SERVER-SQLSEED PLUGIN

**Generated:** 2026-06-21

## OVERVIEW

MCP (Model Context Protocol) server for sqlseed. Exposes schema inspection, AI-powered YAML generation, and data filling as MCP tools.

## STRUCTURE

```
mcp-server-sqlseed/
├── src/mcp_server_sqlseed/
│   ├── __init__.py                   # main() entry point
│   ├── __main__.py                   # python -m support
│   ├── config.py                     # MCPServerConfig (Pydantic)
│   └── server.py                     # FastMCP server, 1 resource + 6 tools
├── tests/                            # pytest suite (test_server.py, test_validate_db_path.py)
├── README.md                         # English documentation
├── README.zh-CN.md                   # Chinese documentation
├── AGENTS.md                         # This file
├── pyproject.toml                    # Package config: sqlseed>=0.1.0,<2, mcp>=1.0,<2
└── uv.lock                           # Lock file (auto-generated)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add MCP tool | `server.py` | Decorate with `@mcp.tool()` |
| Add MCP resource | `server.py` | Decorate with `@mcp.resource()` |
| Modify config | `config.py` | MCPServerConfig Pydantic model |
| Entry point | `__init__.py` | `main()` runs `mcp.run()` |
| Run as module | `__main__.py` | `python -m mcp_server_sqlseed` |

## MCP TOOLS

The server exposes 1 resource + 6 tools:

| Tool | Description |
|------|-------------|
| `sqlseed_inspect_schema` | Inspect database schema (tables, columns, indexes) |
| `sqlseed_generate_yaml` | Generate YAML config for a table |
| `sqlseed_execute_fill` | Fill a table with generated data |
| `sqlseed_gemma4_analyze` | Use Gemma 4 to analyze schema and generate config |
| `sqlseed_gemma4_agent_fill` | Use Gemma 4 agent to fill table end-to-end |
| `sqlseed_list_gemma_models` | List available Gemma 4 model variants |

## CONVENTIONS

- **MCP framework**: FastMCP from `mcp.server.fastmcp`
- **Entry point**: `mcp-server-sqlseed` console script → `main()`
- **AI optional**: `_AI_AVAILABLE` flag guards sqlseed-ai imports
- **Validation**: `_validate_db_target()`, `_validate_table_name()` before operations
- **Size limit**: `_MAX_YAML_CONFIG_SIZE = 256KB` for YAML input

## ANTI-PATTERNS

- **NEVER** import sqlseed_ai at module top → use try/except with `_AI_AVAILABLE` flag
- **NEVER** skip path/table validation before DB operations
- **ALWAYS** return dict from `@mcp.tool()` functions (JSON-serializable)
- **ALWAYS** handle `(ValueError, RuntimeError, OSError)` in tool functions
