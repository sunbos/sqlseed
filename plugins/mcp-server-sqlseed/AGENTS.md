# MCP-SERVER-SQLSEED PLUGIN

## OVERVIEW

MCP (Model Context Protocol) server for sqlseed. Exposes schema inspection, AI-powered YAML generation, and data filling as MCP tools.

## STRUCTURE

```
mcp-server-sqlseed/
├── pyproject.toml                    # Separate package: sqlseed>=0.1.0, mcp>=1.0
└── src/mcp_server_sqlseed/
    ├── __init__.py                   # main() entry point
    ├── __main__.py                   # python -m support
    ├── config.py                     # MCPServerConfig (Pydantic)
    └── server.py                     # FastMCP server, 3 tools (190 lines)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add MCP tool | `server.py` | Decorate with `@mcp.tool()` |
| Add MCP resource | `server.py` | Decorate with `@mcp.resource()` |
| Modify config | `config.py` | MCPServerConfig Pydantic model |
| Entry point | `__init__.py` | `main()` runs `mcp.run()` |

## CONVENTIONS

- **MCP framework**: FastMCP from `mcp.server.fastmcp`
- **Entry point**: `mcp-server-sqlseed` console script → `main()`
- **AI optional**: `_AI_AVAILABLE` flag guards sqlseed-ai imports
- **Validation**: `_validate_db_path()`, `_validate_table_name()` before operations
- **Size limit**: `_MAX_YAML_CONFIG_SIZE = 256KB` for YAML input

## ANTI-PATTERNS

- **NEVER** import sqlseed_ai at module top → use try/except with `_AI_AVAILABLE` flag
- **NEVER** skip path/table validation before DB operations
- **ALWAYS** return dict from `@mcp.tool()` functions (JSON-serializable)
- **ALWAYS** handle `(ValueError, RuntimeError, OSError)` in tool functions
