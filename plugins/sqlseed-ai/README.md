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

These instructions target version 0.2.5. Check [Releases](https://github.com/sunbos/sqlseed/releases)
for publication status; use the source installation below to test an unpublished candidate.
Use a Python 3.10+ virtual environment:

```bash
python -m pip install "sqlseed-ai==0.2.5"
```

Core 0.2.4 and older lack the shared diagnostic interfaces required by this version.
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

Single-table `ai-suggest` checks that the target exists before contacting the
model. Suggestions and cached results must name that same table, including when
using `--no-verify` or `--max-retries 0`. SQLite case aliases remain supported;
export preserves real table and column names, including leading punctuation.
Rejected suggestions leave existing output files unchanged.

The prompt requests one JSON object configuring only the named table, preserving
its table and column names. Other table names are reference context, not additional
output targets; the response still passes target validation.

Direct analysis (`--no-verify` or `--max-retries 0`), streaming or non-streaming,
reports empty replies, invalid JSON, output-limit truncation, and empty configuration
objects separately, without
echoing the model response in these diagnostics. It announces a retry only when
another existing shorter-prompt level remains. Once those levels are exhausted,
it reports the final cause and exits unsuccessfully; it does not increase the
request budget or change the existing output YAML or database.

Direct Python callers can pass `preserve_names=True` to
`SchemaAnalyzer.call_llm()` or `call_llm_streaming()` before validating against
their schema. The default retains the existing leading-punctuation cleanup.

`auto-heal --config` reads that document. An explicit `--db` or `--url` selects the
output connection. Invalid YAML, configuration structure, or unknown input tables
fail without replacing the output file. Candidate repairs are checked for config
shape, builtin generators, parameter names and annotated types, then passed through
the contract validator. Normal preview and execution are still needed to verify
actual generated values and database constraints.

## AI MCP server

The AI MCP entry point requires the `mcp` extra:

```bash
python -m pip install "sqlseed-ai[mcp]==0.2.5"
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

AI requests to `localhost` and loopback IP addresses connect directly even when
an HTTP proxy is configured. Remote services keep the environment proxy settings;
`SSL_CERT_FILE` and `SSL_CERT_DIR` remain effective for HTTPS certificate validation.

For Python callers, `SchemaAnalyzer.call_llm(..., strict_json=True)` and
`call_llm_streaming(..., strict_json=True)` distinguish empty replies, invalid JSON,
and output-limit truncation using content-free `JSONResponseError.code` values.
JSON parsing can complete missing final `}` or `]`
delimiters, including inside code fences, but never fills missing values or strings.
An output-limit response is rejected even if its prefix parses, including a streaming
length marker in a separate empty terminal chunk. Both methods default to
`strict_json=False`. Strict local calls request JSON sampling constraints: LM Studio
uses its JSON-schema grammar interface, and Ollama uses JSON object mode. A server
that explicitly rejects the format gets one text-mode compatibility attempt;
the same strict parser still rejects invalid or truncated output. The CLI's direct
path and both refiner modes keep their existing prompt/refinement retry budgets.
Strict tool calling also rejects arrays, scalars and `null` arguments as `invalid_json`;
compatibility mode may still fall back to response text. Parsed suggestions still
require scope and rule validation.

Single-table suggestion caches use a versioned hash of sorted column names, encoded
as a JSON array so names containing delimiters remain distinct. The check detects
added, removed, or renamed columns; column order, types, and constraints are not
included. Caches using the older delimiter encoding are ignored and regenerated.
Use `--no-cache` to analyze again without cached suggestions. This cache check is
separate from AutoHeal's full schema fingerprint. Malformed cache metadata
or configuration containers are treated as cache misses. Review model output before
writing data.

## Hardware estimates on macOS

The AI MCP model list distinguishes Apple unified memory, Intel shared graphics
memory, and dedicated GPU memory. Apple unified RAM is not reported as dedicated
VRAM or added to system RAM. `unified_memory_budget_gb` is a static heuristic:
`max(0, min(total_ram_gb * 0.75, total_ram_gb - 4))`, reserving at least 4 GiB or
25% for the system. It is not measured free memory or a Metal allocation limit.

For an identified Apple GPU on macOS, model screening compares that budget with
both existing minimum RAM and VRAM estimates and reports at most `capable`.
This does not verify Metal acceleration, backend/model support, or successful
inference; loaded applications and context size can require more memory.

## Requirements

These metadata requirements apply to version 0.2.5 and its source candidates.
Use local Core and plugins together when developing from source.

- Python `>=3.10`
- `sqlseed>=0.2.5.dev0,<0.3`
- `sqlseed-cli>=0.2.4.dev0,<0.3`
- `openai>=1.55.3` (SDK transport defaults with HTTPX 0.28 compatibility)
- `httpx>=0.24.0`
- `networkx>=3.0`
- Optional `mcp` extra: `mcp>=1.0,<2`
- A reachable, configured backend for actual model requests

See the [AI integration guide](https://sunbos.github.io/sqlseed/gemma4-integration/),
[migration guide](https://sunbos.github.io/sqlseed/migration/), and
[configuration source](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/src/sqlseed_ai/config.py).

License: [AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE).
The distribution includes the full LICENSE text.
