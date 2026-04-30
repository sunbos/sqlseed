# sqlseed-ai

AI-powered data generation plugin for [sqlseed](https://github.com/sunbos/sqlseed).

LLM-driven schema analysis, self-correcting config generation, and template pool assistance. Uses OpenAI-compatible API (default: OpenRouter free models).

## Installation

```bash
pip install sqlseed-ai
```

## Quick Start

```bash
# Set API key (OpenRouter, OpenAI, DeepSeek, etc.)
export SQLSEED_AI_API_KEY="your-api-key"

# Generate AI-suggested YAML config
sqlseed ai-suggest app.db --table users --output users.yaml

# With self-correction (3 rounds by default)
sqlseed ai-suggest app.db --table users --output users.yaml --verify

# Specify model
sqlseed ai-suggest app.db --table users -o users.yaml --model deepseek/deepseek-chat

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

Queries OpenRouter API to find the best available free model. Falls back through a priority list:

```
nvidia/nemotron-3-super-120b-a12b:free → tencent/hy3-preview:free → ...
```

Result cached for 1 hour. Skip auto-selection by specifying `--model` or `SQLSEED_AI_MODEL`.

### Template Pool

When sqlseed fills a table with `skip_ai=False`, the plugin pre-generates candidate values for columns that can't be mapped to a deterministic generator (via `sqlseed_pre_generate_templates` hook).

### File Caching

AI configs cached in `.sqlseed_cache/ai_configs/` with schema hash validation. Schema changes auto-invalidate cache. Use `--no-cache` to skip.

## Configuration

### Environment Variables

| Variable | Fallback | Default | Description |
|:---------|:---------|:--------|:------------|
| `SQLSEED_AI_API_KEY` | `OPENAI_API_KEY` | — | API key (required) |
| `SQLSEED_AI_BASE_URL` | `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` | API endpoint |
| `SQLSEED_AI_MODEL` | — | auto-select | Model name |
| `SQLSEED_AI_TIMEOUT` | — | `60` | API timeout (seconds) |

### CLI Options

```
--model, -m       Model name (overrides auto-selection)
--api-key         API key (overrides env)
--base-url        API base URL (overrides env)
--max-retries     Self-correction rounds (default: 3, 0=disable)
--verify/--no-verify  Toggle self-correction (default: verify)
--no-cache        Skip file cache
--timeout         API timeout in seconds (default: 120)
```

## Plugin Hooks

This plugin registers via `[project.entry-points."sqlseed"]` and implements:

| Hook | Purpose |
|:-----|:--------|
| `sqlseed_ai_analyze_table` | LLM-driven table analysis, returns column configs |
| `sqlseed_pre_generate_templates` | Pre-generate candidate values for complex columns |
| `sqlseed_register_providers` | Placeholder (no-op, entry-point registration) |
| `sqlseed_register_column_mappers` | Placeholder (no-op, entry-point registration) |

## Requirements

- Python >= 3.10
- `sqlseed >= 0.1.0`
- `openai >= 1.0`
- An OpenAI-compatible API key

## License

AGPL-3.0-or-later
