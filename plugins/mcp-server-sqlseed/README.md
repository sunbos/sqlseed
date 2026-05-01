# mcp-server-sqlseed

**[English](README.md)** | [中文](README.zh-CN.md)

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for [sqlseed](https://github.com/sunbos/sqlseed) — enabling AI assistants to inspect schemas, generate configs, and fill SQLite databases.

## Installation

```bash
# Basic
pip install mcp-server-sqlseed

# With AI support (includes sqlseed-ai)
pip install mcp-server-sqlseed[ai]
```

## Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or equivalent:

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    }
  }
}
```

### Cursor / Other MCP Clients

Use command: `mcp-server-sqlseed`

## MCP Tools

| Tool | Description |
|:-----|:------------|
| `sqlseed_inspect_schema` | Inspect database schema: columns, foreign keys, indexes, sample data, schema_hash. Accepts optional `table_name` (all tables if omitted). |
| `sqlseed_generate_yaml` | AI-driven YAML config generation with self-correction. Requires `sqlseed-ai` plugin and API key. Supports `api_key`/`base_url`/`model` parameter overrides. |
| `sqlseed_execute_fill` | Execute data generation. Accepts optional `yaml_config` string, `count`, and `enrich` flag. Max YAML config size: 256KB. |

### MCP Resource

| Resource | Description |
|:---------|:------------|
| `sqlseed://schema/{db_path}/{table_name}` | Read-only JSON schema for a specific table |

## Example Usage

After configuring your MCP client, you can prompt:

> "Inspect the schema of `app.db`, generate a YAML config for the `users` table, then fill 1000 rows."

The AI assistant will call:
1. `sqlseed_inspect_schema` → get table structure
2. `sqlseed_generate_yaml` → generate YAML config (if sqlseed-ai is installed)
3. `sqlseed_execute_fill` → fill data

## AI Integration

When `sqlseed-ai` is installed and an API key is configured (`SQLSEED_AI_API_KEY` or `OPENAI_API_KEY`), the `sqlseed_generate_yaml` tool uses LLM-driven analysis with self-correction. Without the AI plugin, the tool returns a fallback message.

## Requirements

- Python >= 3.10
- `sqlseed >= 0.1.0`
- `mcp >= 1.0`

Optional:
- `sqlseed-ai` (for `sqlseed_generate_yaml` tool)

## License

AGPL-3.0-or-later
