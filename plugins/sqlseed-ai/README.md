# sqlseed-ai

AI-powered data generation plugin for [sqlseed](https://github.com/sunbos/sqlseed).

## Overview

`sqlseed-ai` extends `sqlseed` with LLM-driven schema analysis, self-correcting config generation, and template-oriented AI assistance. The current public workflow centers on generating table-level YAML suggestions via `sqlseed ai-suggest`.

### Features

- **Schema Analysis** — LLM-powered table structure understanding via `SchemaAnalyzer`
- **AI Config Refiner** — Self-correcting feedback loop with up to 3 retry rounds
- **Template Pool Assistance** — Pre-generate candidate values for hard-to-map columns via plugin hooks
- **Few-shot Examples** — Built-in example library for improved LLM output quality
- **CLI And MCP Integration** — Shared AI suggestion flow for `sqlseed ai-suggest` and the MCP server

## Installation

```bash
pip install sqlseed-ai
```

## Quick Start

```bash
# Generate AI-suggested YAML config for a table
sqlseed ai-suggest test.db --table users --output users.yaml
```

## Requirements

- Python >= 3.10
- `sqlseed >= 0.1.0`
- An OpenAI-compatible API key (set via `OPENAI_API_KEY` environment variable)

## License

AGPL-3.0-or-later
