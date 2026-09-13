# Gemma 4 Integration Guide

`sqlseed-ai` is the optional AI plugin, with Gemma 4 as its long-term model
backend direction. This page describes backend configuration, structured
responses, and the separate AI MCP entry point on `main`. Install a compatible
package set using the [migration guide](migration.md). Core remains offline.

## Registered Model IDs

| Model | Variant | Backend examples | Intended use |
|-------|---------|-------------------|----------|
| `gemma-4-e2b-it` | E2B (2B Effective, Edge) | Ollama / LM Studio | Ultra-light edge deployment |
| `gemma-4-e4b-it` | E4B (4B Effective, Edge) | LM Studio | Local schema analysis |
| `gemma-4-12b-it` | 12B Unified | LM Studio / Ollama | Balanced quality and speed |
| `gemma-4-26b-a4b-it` | 26B A4B MoE | Google AI Studio | Complex analysis + self-correction |
| `gemma-4-31b-it` | 31B Dense | Google AI Studio | Dense model option |

The registry supports model ID conversion and candidate selection. It does not
prove that a service currently hosts a model or that every combination has been
validated against a real model. Check the endpoint model list and verify a small
request before relying on it.

## Backend Configuration

### Google AI Studio (Cloud)

```bash
export SQLSEED_AI_BACKEND=google_ai_studio
export GOOGLE_API_KEY=your-key
# Model defaults to gemma-4-26b-a4b-it
```

An API key alone does not select Google AI Studio. `SQLSEED_AI_BACKEND` takes
priority over URL inference. Without an explicit backend or a recognized URL,
`openai_compat` is used and requires `SQLSEED_AI_BASE_URL`. Set
`SQLSEED_AI_MODEL` to a model available from the selected service.

### LM Studio (Local GUI)

```bash
export SQLSEED_AI_BACKEND=lm_studio
export SQLSEED_AI_MODEL=google/gemma-4-e4b
# Ensure LM Studio is running with a Gemma 4 model loaded
```

### Ollama (Local CLI)

```bash
export SQLSEED_AI_BACKEND=ollama
export SQLSEED_AI_MODEL=gemma4:e4b
# Ensure Ollama is running: ollama pull gemma4:e4b
```

## Native Function Calling

sqlseed-ai defines a single function interface via `GEMMA_TOOLS` (one tool: `analyze_schema`):

### analyze_schema

Analyzes a database table schema and recommends data generation configuration.

```python
GEMMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_schema",
            "description": "Analyze a database table schema and recommend data generation configuration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                    "columns": {"type": "array", "items": {...}},
                    "foreign_keys": {"type": "array", "items": {...}},
                    "indexes": {"type": "array", "items": {...}},
                },
                "required": ["table_name", "columns"],
            },
        },
    }
]
```

### Calling Flow

The active strategy is resolved per backend via `AIConfig.resolve_tool_calling_protocol()`:

```
1. Native function calling (tools=GEMMA_TOOLS, tool_choice="auto") is attempted
   only when the resolved protocol is "gemma4" (Google AI Studio only) or
   "openai" (Google AI Studio / OpenAI-compatible).
2. Gemma 4 selects the analyze_schema function, returns structured parameters
3. Extract JSON from tool_call.function.arguments
4. Fallback: cloud backends (Google AI Studio / OpenAI-compatible) use JSON mode
   (response_format: json_object); local backends (LM Studio, Ollama) use
   plain-text mode directly.
```

## Configuration Validation and Repair

Single-table `ai-suggest` uses the bounded `AiConfigRefiner` correction loop.
This is not persistent agent memory:

```
Gemma 4 generates initial config
    -> Validate (type check, constraint check, dependency integrity)
    -> If errors found:
        -> Feed error messages back to Gemma 4
        -> Gemma 4 corrects the config
        -> Re-validate (up to 3 rounds)
    -> Return a candidate config for review; execution depends on the entry point
```

`ai-analyze` defaults to `AutoHealOrchestrator`, and `auto-heal` repairs an
existing YAML configuration through contract-driven self-healing. See the
[CLI guide](guide.md#cli-reference) for their options.

## MCP Server Tools

With a compatible `sqlseed-ai[mcp]` installation, the separate
`mcp-server-sqlseed-ai` process exposes `sqlseed_ai_generate_yaml` plus the three
Gemma-specific tools below. Installing AI does not add tools to the two-tool
rule-driven `mcp-server-sqlseed` process. Configure each server separately; see
the [MCP guide](guide.md#mcp-server) for a complete client configuration.

| Tool | Description |
|------|-------------|
| `sqlseed_gemma4_analyze` | Analyze schema with the configured model and supported response protocol |
| `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow (analyze -> config -> fill) |
| `sqlseed_list_gemma_models` | List registered Gemma 4 variants, hardware compatibility, and backend status |

## Quick Start

Install Core/CLI/AI from one compatible source using the
[installation guide](guide.md#installation), and prepare the database tables.
After configuring one backend above:

```bash
sqlseed ai-suggest app.db -t users -o config.yaml
sqlseed ai-analyze --db app.db -o database-rules.yaml
```

For single-table Python analysis:

```python
from sqlseed_ai import SchemaAnalyzer
from sqlseed_ai.config import AIConfig
from sqlseed.core.orchestrator import DataOrchestrator

config = AIConfig.from_env()
analyzer = SchemaAnalyzer(config=config)

with DataOrchestrator("app.db") as orch:
    schema_ctx = orch.get_schema_context("users")
result = analyzer.analyze_table_from_ctx(**schema_ctx)
```

## Performance and Verification

Analysis time depends on hardware, model, schema scope, prompt, timeout settings,
and backend load. Record those conditions with measured results. Fixed-response
regressions validate local processing, not model connectivity or suggestion
quality. This guide does not promise general latency figures without reproducible
experiment conditions.
