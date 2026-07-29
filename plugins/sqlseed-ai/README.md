# sqlseed-ai

**[English](README.md)** | [中文](README.zh-CN.md)

AI-powered data generation plugin for [sqlseed](https://github.com/sunbos/sqlseed).

LLM-driven schema analysis, self-correcting config generation, and template pool assistance. Supports multiple backends: Google AI Studio (Gemma 4 Native Function Calling), LM Studio, Ollama, and any OpenAI-compatible API (OpenRouter, OpenAI, DeepSeek, etc.).

## Installation

```bash
pip install sqlseed-ai
```

## Quick Start

```bash
# Set API key (or use GOOGLE_API_KEY for Google AI Studio)
export SQLSEED_AI_API_KEY="your-api-key"

# Generate AI-suggested YAML config
sqlseed ai-suggest app.db --table users --output users.yaml

# With self-correction (3 rounds by default)
sqlseed ai-suggest app.db --table users --output users.yaml --verify

# Specify model (defaults to Gemma 4 26B via Google AI Studio)
sqlseed ai-suggest app.db --table users -o users.yaml --model gemma-4-26b-a4b-it

# Use local LM Studio (backend is selected via env var)
export SQLSEED_AI_BACKEND=lm_studio
sqlseed ai-suggest app.db --table users -o users.yaml --model google/gemma-4-e4b

# Skip cache
sqlseed ai-suggest app.db --table users -o users.yaml --no-cache
```

## Features

### Schema Analyzer

`SchemaAnalyzer` extracts rich context from your database (columns, indexes, sample data, foreign keys, data distribution) and builds a structured prompt for LLM analysis. Returns column-level generation configs as JSON.

### Self-Correcting Refiner

`AiConfigRefiner` validates LLM output against actual schema:
1. LLM generates column config
2. Refiner checks for unknown generators, type mismatches, expression errors
3. If errors found, sends correction request back to LLM
4. Up to 3 retry rounds, then raises `AISuggestionFailedError`

### Auto Model Selection

When using the `google_ai_studio` backend (default), the `GemmaModel` enum provides pre-configured Gemma 4 variants. The model is selected based on the backend:

1. **Google AI Studio**: Defaults to `gemma-4-26b-a4b-it` (recommended balance of quality and speed).
2. **LM Studio / Ollama**: User must specify a loaded model via `--model` or `SQLSEED_AI_MODEL`.
3. **OpenAI-compatible** (OpenRouter, DeepSeek, etc.): User must specify both `--model` and `--base-url`.

For **OpenRouter free models**, set:
```bash
export SQLSEED_AI_BACKEND=openai_compat
export SQLSEED_AI_BASE_URL=https://openrouter.ai/api/v1
export SQLSEED_AI_MODEL=<free-model-name>
```

Skip auto-selection by specifying `--model` or `SQLSEED_AI_MODEL`.

When using the `google_ai_studio` backend, the `GemmaModel` enum provides pre-configured Gemma 4 variants:

| Enum Value | Model ID | Description |
|:-----------|:---------|:------------|
| `GemmaModel.GEMMA_4_E2B` | `gemma-4-e2b-it` | 2B Effective, Edge — Ultra-light edge deployment |
| `GemmaModel.GEMMA_4_E4B` | `gemma-4-e4b-it` | 4B Effective, Edge — Lightweight local inference |
| `GemmaModel.GEMMA_4_12B` | `gemma-4-12b-it` | 12B Unified, Laptop — Balanced quality and speed |
| `GemmaModel.GEMMA_4_26B_A4B` | `gemma-4-26b-a4b-it` | 26B A4B MoE — High quality, recommended |
| `GemmaModel.GEMMA_4_31B` | `gemma-4-31b-it` | 31B Dense — Best quality, largest model |

The `AIBackend` enum selects the API backend:

| Enum Value | Backend | Default Base URL |
|:-----------|:--------|:-----------------|
| `AIBackend.GOOGLE_AI_STUDIO` | Google AI Studio | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `AIBackend.LM_STUDIO` | LM Studio | `http://127.0.0.1:1234/v1` |
| `AIBackend.OLLAMA` | Ollama | `http://localhost:11434/v1` |
| `AIBackend.OPENAI_COMPAT` | OpenAI-compatible | (must set `SQLSEED_AI_BASE_URL`) |

### Template Pool

When sqlseed fills a table with `skip_ai=False`, the plugin pre-generates candidate values for columns that can't be mapped to a deterministic generator (via `sqlseed_pre_generate_templates` hook).

### File Caching

AI configs cached in platform-specific cache directory (`~/Library/Caches/sqlseed/ai_configs/` on macOS, `~/.cache/sqlseed/ai_configs/` on Linux, `%LOCALAPPDATA%/sqlseed/ai_configs/` on Windows) with schema hash validation. Schema changes auto-invalidate cache. Use `--no-cache` to skip. Override with `SQLSEED_CACHE_DIR` environment variable.

## Configuration

### Environment Variables

| Variable | Fallback | Default | Description |
|:---------|:---------|:--------|:------------|
| `SQLSEED_AI_API_KEY` | `OPENAI_API_KEY` | — | API key (required) |
| `SQLSEED_AI_BASE_URL` | `OPENAI_BASE_URL` | (auto by backend) | API endpoint |
| `SQLSEED_AI_MODEL` | — | `gemma-4-26b-a4b-it` | Model name |
| `SQLSEED_AI_TIMEOUT` | — | `0` (auto) | API timeout in seconds (0 = auto-resolve per backend) |
| `SQLSEED_AI_BACKEND` | — | `google_ai_studio` | AI backend: `google_ai_studio`, `lm_studio`, `ollama`, `openai_compat` |
| `GOOGLE_API_KEY` | — | — | Google AI Studio API key (required when backend is `google_ai_studio`) |

### CLI Options

```
--model, -m       Model name (overrides auto-selection)
--api-key         API key (overrides env)
--base-url        API base URL (overrides env)
--max-retries     Self-correction rounds (default: 3, 0=disable)
--verify/--no-verify  Toggle self-correction (default: verify)
--no-cache        Skip file cache
--timeout         API timeout in seconds (default: 0 = auto)
```

## Plugin Hooks

This plugin registers via `[project.entry-points."sqlseed"]` and implements:

| Hook | Purpose |
|:-----|:--------|
| `sqlseed_ai_analyze_table` | LLM-driven table analysis, returns column configs |
| `sqlseed_pre_generate_templates` | Pre-generate candidate values for complex columns |

## Requirements

- Python >= 3.10
- `sqlseed >= 0.1.0`
- `openai >= 1.0`
- `httpx >= 0.24.0`
- An OpenAI-compatible API key or Google AI Studio API key

## Gemma 4 Integration

When using the `google_ai_studio` backend, sqlseed-ai leverages **Gemma 4 Native Function Calling** for structured schema analysis:

### GEMMA_TOOLS

The plugin defines a `GEMMA_TOOLS` function declaration that tells Gemma 4 how to respond with structured schema analysis. Instead of parsing free-form text, the model is instructed to call an `analyze_schema` function with typed parameters (table name, columns, foreign keys, indexes), ensuring output conforms to the expected schema.

### Native Function Calling Mechanism

1. **Tool Definition**: `GEMMA_TOOLS` declares an `analyze_schema` function with a strict JSON Schema describing each parameter (table_name, columns — each with name/type/is_primary_key/is_autoincrement/nullable/default — foreign_keys, indexes).
2. **Request**: The schema context and analysis prompt are sent to the Gemma 4 model with `tools=GEMMA_TOOLS` and `tool_choice="auto"`. If the endpoint does not support tool calling, the plugin automatically falls back to JSON mode (`response_format: {"type": "json_object"}`).
3. **Response Parsing**: When the model invokes the tool, the plugin extracts the structured args directly from the `analyze_schema` tool call — no regex or fragile parsing needed.
4. **Validation**: The extracted args are passed through the same `AiConfigRefiner` pipeline for self-correction.

This approach significantly improves reliability over text-based LLM output parsing, as the model is constrained to produce well-formed, schema-compliant responses.

## License

AGPL-3.0-or-later
