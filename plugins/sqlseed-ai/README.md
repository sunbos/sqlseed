# sqlseed-ai

**[English](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/README.md)** |
[中文](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/README.zh-CN.md)

Optional LLM schema analysis and contract-driven configuration repair for
[sqlseed](https://sunbos.github.io/sqlseed/). The plugin suggests column rules,
validates and repairs configurations, and can prepare template values. Accepted
configurations can be executed offline by Core.

Supported backend adapters are Google AI Studio, LM Studio, Ollama, and
OpenAI-compatible APIs. Model availability and response quality require a real
backend test; installing the plugin does not perform one.

## Installation

For the 0.2.4 release, use a Python 3.10+ virtual environment:

```bash
python -m pip install "sqlseed-ai==0.2.4"
```

Core 0.2.3 lacks the plugin hooks and target-validation interfaces used here.
For development, install Core and the required local plugins together from the
repository root:

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e ./plugins/sqlseed-ai
```

## CLI quick start

Configure a backend, an available model, and credentials as needed by that service.
For an OpenAI-compatible endpoint, for example:

```bash
export SQLSEED_AI_BACKEND=openai_compat
export SQLSEED_AI_BASE_URL="https://your-service.example/v1"
export SQLSEED_AI_MODEL="your-available-model"
export SQLSEED_AI_API_KEY="your-api-key"
```

Create the SQLite tables before analysis:

```bash
# Analyze one table and validate the suggested configuration
sqlseed ai-suggest app.db --table users --output users.yaml --verify --no-cache

# Analyze all tables with the v4 AutoHealOrchestrator
sqlseed ai-analyze --db app.db --output config.yaml

# Repair an existing configuration
sqlseed auto-heal --db app.db --config broken.yaml --output healed.yaml

# After reviewing the generated rules, execute them offline
sqlseed fill --config users.yaml --no-ai
```

| Command | Behavior |
|---|---|
| `ai-suggest` | Single-table LLM analysis and optional self-correction; `--auto-heal` uses the AutoHeal path |
| `ai-analyze` | Full or selected-table analysis with dependency scope and configuration merge options |
| `auto-heal` | Repair the supplied YAML while preserving its scope, counts, seeds, and unaffected rules |

`ai-analyze --tables orders` includes referenced parents up to `--max-depth 5`.
`--no-dependencies` or `--max-depth 0` limits the scope to named tables. Unknown table
names fail before output is written. `--merge` requires `--output`; it replaces
selected tables, retains existing dependency and unrelated tables plus root settings,
and appends missing generated tables.

`auto-heal --config` reads that document. An explicit `--db` or `--url` selects the
output connection. Invalid YAML, configuration structure, or unknown input tables
fail without replacing the output file. Candidate repairs are checked for config
shape, builtin generators, parameter names and annotated types, then passed through
the contract validator. Normal preview and execution are still needed to verify
actual generated values and database constraints.

## AI MCP server

The AI MCP entry point requires the `mcp` extra:

```bash
python -m pip install "sqlseed-ai[mcp]==0.2.4"
mcp-server-sqlseed-ai
```

For a source checkout, use `python -m pip install -e . -e ./plugins/sqlseed-cli -e "./plugins/sqlseed-ai[mcp]"`.
Configure an MCP client to launch
`mcp-server-sqlseed-ai`. It exposes:

- `sqlseed_ai_generate_yaml`
- `sqlseed_gemma4_analyze`
- `sqlseed_gemma4_agent_fill`
- `sqlseed_list_gemma_models`

For deterministic YAML generation and data filling without an LLM, use the separate
[Core MCP package](https://github.com/sunbos/sqlseed/tree/main/plugins/mcp-server-sqlseed).
MCP discovery or a successful model list does not establish that inference works.

## Configuration and caching

| Variable | Purpose |
|---|---|
| `SQLSEED_AI_BACKEND` | `google_ai_studio`, `lm_studio`, `ollama`, or `openai_compat` |
| `SQLSEED_AI_BASE_URL` | Service endpoint; falls back to `OPENAI_BASE_URL` |
| `SQLSEED_AI_MODEL` | Model identifier exposed by the selected service |
| `SQLSEED_AI_API_KEY` | Credentials; falls back to `GOOGLE_API_KEY`, then `OPENAI_API_KEY` |
| `SQLSEED_AI_TIMEOUT` | Request timeout in seconds |
| `SQLSEED_CACHE_DIR` | Override the platform-specific sqlseed cache directory |

Configuration is loaded through `AIConfig.from_env()`. Backend resolution uses the
explicit backend, then known URL patterns, then OpenAI-compatible behavior. It does
not probe every service as a fallback chain. The `tool_calling_protocol` setting and
its resolver choose the response protocol; a model name alone is insufficient.

AI configuration caches include schema hashes. Schema changes invalidate cached
suggestions; `--no-cache` bypasses them. Review model output before writing data.

## Requirements

- Python `>=3.10`
- `sqlseed>=0.2.4.dev0,<0.3`
- `sqlseed-cli>=0.2.4.dev0,<0.3`
- `openai>=1.0`
- `httpx>=0.24.0`
- `networkx>=3.0`
- Optional `mcp` extra: `mcp>=1.0,<2`
- A reachable, configured backend for actual model requests

See the [AI integration guide](https://sunbos.github.io/sqlseed/gemma4-integration/),
[migration guide](https://sunbos.github.io/sqlseed/migration/), and
[configuration source](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/src/sqlseed_ai/config.py).

License: [AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE).
The distribution includes the full LICENSE text.
