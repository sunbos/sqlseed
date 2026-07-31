# MCP-SERVER-SQLSEED PLUGIN

**Last updated:** 2026-07-12

## OVERVIEW

MCP (Model Context Protocol) server for sqlseed. Exposes **core capabilities only** (rule-driven YAML template generation + data fill). No LLM dependency. Per ARCHITECTURE.md Section 3.4, schema inspection and AI-driven analysis live in separate packages.

## STRUCTURE

```
mcp-server-sqlseed/
├── src/mcp_server_sqlseed/
│   ├── __init__.py                   # main() entry point
│   ├── __main__.py                   # python -m support
│   ├── config.py                     # MCPServerConfig (Pydantic)
│   └── server.py                     # FastMCP server, 2 tools (no resources)
├── tests/                            # pytest suite (test_server.py, test_validate_db_path.py, test_config.py)
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
| Modify config | `config.py` | MCPServerConfig Pydantic model |
| Entry point | `__init__.py` | `main()` runs `mcp.run()` |
| Run as module | `__main__.py` | `python -m mcp_server_sqlseed` |

## MCP TOOLS

The server exposes 2 tools (no resources):

| Tool | Description |
|------|-------------|
| `sqlseed_generate_yaml` | Rule-driven YAML config template via core `ColumnMapper` (no LLM) |
| `sqlseed_execute_fill` | Fill a table with generated data |

### Moved to `sqlseed-ai[mcp]`

The following tools now live in the `sqlseed-ai` package's MCP module (`sqlseed_ai.mcp`):
- `sqlseed_ai_generate_yaml` (LLM-driven YAML generation)
- `sqlseed_gemma4_analyze`
- `sqlseed_gemma4_agent_fill`
- `sqlseed_list_gemma_models`

### Removed (delegated to third-party MCPs)

- `sqlseed_inspect_schema` — use mcp-database-server / mcp-db-analyzer
- `sqlseed://schema` Resource — schema inspection by other MCPs

## CONVENTIONS

- **MCP framework**: FastMCP from `mcp.server.fastmcp`
- **Entry point**: `mcp-server-sqlseed` console script → `main()`
- **No AI dependency**: this package never imports `sqlseed_ai`
- **Validation**: `_validate_db_target()`, `_validate_table_name()` before operations
- **Size limit**: `_MAX_YAML_CONFIG_SIZE = 256KB` for YAML input

## ANTI-PATTERNS

- **NEVER** import sqlseed_ai in this package — AI tools belong in `sqlseed-ai[mcp]`
- **NEVER** skip path/table validation before DB operations
- **ALWAYS** return dict from `@mcp.tool()` functions (JSON-serializable)
- **ALWAYS** handle `(ValueError, RuntimeError, OSError)` in tool functions
