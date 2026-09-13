# mcp-server-sqlseed

**[English](https://github.com/sunbos/sqlseed/blob/main/plugins/mcp-server-sqlseed/README.md)** |
[中文](https://github.com/sunbos/sqlseed/blob/main/plugins/mcp-server-sqlseed/README.zh-CN.md)

[Model Context Protocol](https://modelcontextprotocol.io/) tools for
[sqlseed](https://sunbos.github.io/sqlseed/): derive a YAML configuration from database
schema, then generate test data. Both tools use offline Core rules and require no LLM.

## Installation

These instructions describe the current five-package checkout. Until the matching
release is available on PyPI, install local Core and MCP together from the repository
root in a Python 3.10+ virtual environment:

```bash
python -m pip install -e . -e ./plugins/mcp-server-sqlseed
```

Core 0.2.3 lacks the target-validation interfaces used here. Once matching packages
are published, the package-index installation is:

```bash
python -m pip install "mcp-server-sqlseed>=0.2.4.dev0,<0.3"
```

## MCP client configuration

Use the executable from the environment where the package is installed:

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    }
  }
}
```

If the client does not inherit that environment's PATH, use the executable's absolute
path. The server runs over stdio. `python -m mcp_server_sqlseed` is also supported.

## Tools

| Tool | Input and result |
|---|---|
| `sqlseed_generate_yaml` | Takes `db_path` and `table_name`; returns a rule-driven YAML string |
| `sqlseed_execute_fill` | Takes `db_path`, `table_name`, `count=1000`, optional `yaml_config`, and `enrich=False`; returns the table, committed count, elapsed time, and errors |

The `db_path` argument accepts an existing SQLite `.db`/`.sqlite`/`.sqlite3` file or a
database URL. For PostgreSQL, install the Core `postgres` extra. Tables must already
exist. The schema mapper chooses generators deterministically; no model request is
made by either tool.

When `yaml_config` is supplied, it must be a YAML mapping containing the requested
table. Empty documents, unknown tables, and configurations for a different table fail
before generation. The UTF-8 size limit is 256 KiB. Tool arguments select the database,
table, row count, and enrichment; YAML contributes only the matching table's column
rules, seed, and `clear_before` setting.

A typical client workflow is:

1. Call `sqlseed_generate_yaml` for an existing table.
2. Review the YAML and desired row count.
3. Call `sqlseed_execute_fill` and check its `errors` and committed `count`.

Earlier committed batches can remain after a later batch fails. The YAML tool returns
`# Error: ...` for handled errors; the fill tool returns an `error` field for handled
request failures. Check these in addition to MCP transport success.

## Separate AI MCP server

This package exposes exactly the two tools above. Schema resources and a standalone
schema-inspection tool are not provided. For LLM analysis, install local Core, CLI,
and the AI MCP extra together:

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e "./plugins/sqlseed-ai[mcp]"
mcp-server-sqlseed-ai
```

After matching packages are published, use
`"sqlseed-ai[mcp]>=0.2.4.dev0,<0.3"`. Its YAML tool is
`sqlseed_ai_generate_yaml`; its executable is `mcp-server-sqlseed-ai`. The old
`mcp-server-sqlseed[ai]` installation does not describe the current package layout.

## Requirements

- Python `>=3.10`
- `sqlseed>=0.2.4.dev0,<0.3`
- `mcp>=1.0,<2`

See the [user guide](https://sunbos.github.io/sqlseed/guide/),
[migration guide](https://sunbos.github.io/sqlseed/migration/), and
[server source](https://github.com/sunbos/sqlseed/tree/main/plugins/mcp-server-sqlseed).

License: [AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE).
The distribution includes the full LICENSE text.
