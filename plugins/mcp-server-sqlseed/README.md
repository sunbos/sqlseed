# mcp-server-sqlseed

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for [sqlseed](https://github.com/sunbos/sqlseed) — enabling AI assistants to generate SQLite test data.

## Overview

`mcp-server-sqlseed` exposes sqlseed's capabilities as MCP tools, allowing AI assistants (Claude, Cursor, etc.) to inspect database schemas, generate YAML configurations, and execute data fills seamlessly.

### MCP Tools

| Tool | Description |
|------|-------------|
| `sqlseed_inspect_schema` | Inspect database table structure, columns, indexes, and sample data |
| `sqlseed_generate_yaml` | Generate a YAML configuration file for data generation |
| `sqlseed_execute_fill` | Execute data generation and fill a database table |

### MCP Resource

- `sqlseed://schema/{db_path}/{table_name}` — Read-only schema information for a specific table

## Installation

```bash
pip install mcp-server-sqlseed
```

## Configuration

Add to your MCP client configuration (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    }
  }
}
```

## Requirements

- Python >= 3.10
- `sqlseed >= 0.1.0`
- `mcp >= 1.0`

## License

AGPL-3.0-or-later
