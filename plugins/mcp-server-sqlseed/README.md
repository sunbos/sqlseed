# mcp-server-sqlseed

**[English](README.md)** | [中文](README.zh-CN.md)

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for [sqlseed](https://github.com/sunbos/sqlseed) — exposing **core capabilities** (rule-driven YAML generation + data fill) to AI assistants. No LLM required.

## Installation

```bash
pip install mcp-server-sqlseed
```

For LLM-driven schema analysis, install the separate AI MCP server instead:

```bash
pip install "sqlseed-ai[mcp]"   # provides sqlseed_ai_generate_yaml + Gemma 4 tools
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
| `sqlseed_generate_yaml` | Rule-driven YAML config template generated from the schema via sqlseed's `ColumnMapper` (75 exact rules + 29 regex patterns). Offline, deterministic, no LLM. |
| `sqlseed_execute_fill` | Execute data generation. Accepts optional `yaml_config` string, `count`, and `enrich` flag. Max YAML config size: 256KB. |
| `sqlseed_gemma4_analyze` | Analyze table schema with Gemma 4 Native Function Calling. Supports `model`/`backend` overrides. Requires `sqlseed-ai`. |
| `sqlseed_gemma4_agent_fill` | End-to-end AI agent: Gemma 4 analyzes schema → generates config (self-correction) → fills data. Requires `sqlseed-ai`. |
| `sqlseed_list_gemma_models` | List Gemma 4 model variants with hardware compatibility (RAM/GPU/VRAM), backend availability, and recommended default model/backend. |

### What's NOT included

Per [ARCHITECTURE.md Section 3.4](../../ARCHITECTURE.md), this server exposes core capabilities only:

- ~~`sqlseed_inspect_schema`~~ — use third-party MCPs such as [mcp-database-server](https://github.com/iPraBhu/mcp-database-server) or [mcp-db-analyzer](https://github.com/Dmitriusan/mcp-db-analyzer)
- ~~`sqlseed://schema` Resource~~ — schema inspection is delegated to the MCPs above
- ~~`sqlseed_gemma4_analyze` / `sqlseed_gemma4_agent_fill` / `sqlseed_list_gemma_models`~~ — moved to `sqlseed-ai[mcp]`
- ~~AI-driven `sqlseed_generate_yaml`~~ — the LLM-driven variant is `sqlseed_ai_generate_yaml` in `sqlseed-ai[mcp]`

## Example Usage

After configuring your MCP client, you can prompt:

> "Generate a YAML config for the `users` table in `app.db`, then fill 1000 rows."

The AI assistant will call:
1. `sqlseed_generate_yaml` → rule-driven YAML template (offline)
2. `sqlseed_execute_fill` → fill data

### Gemma 4 Integration

The `sqlseed_gemma4_analyze` and `sqlseed_gemma4_agent_fill` tools leverage **Gemma 4 Native Function Calling** via the `GEMMA_TOOLS` interface (`analyze_schema` tool, with automatic fallback to JSON mode). They work with any backend supported by `sqlseed-ai` (Google AI Studio, LM Studio, Ollama, OpenAI-compatible) and accept optional `model`/`backend` overrides. Use `sqlseed_list_gemma_models` to see available model variants, hardware compatibility, and backend availability.

## Requirements

- Python >= 3.10
- `sqlseed >= 0.1.0`
- `mcp >= 1.0`

## License

AGPL-3.0-or-later
