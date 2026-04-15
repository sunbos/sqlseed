# sqlseed-ai

AI-powered data generation plugin for [sqlseed](https://github.com/sunbos/sqlseed).

## Overview

`sqlseed-ai` extends sqlseed with LLM-driven intelligent data generation capabilities. It analyzes your database schema and produces high-quality, context-aware YAML configuration suggestions.

### Features

- **Schema Analysis** — LLM-powered table structure understanding via `SchemaAnalyzer`
- **AI Config Refiner** — Self-correcting feedback loop with up to 3 retry rounds
- **Column-level Suggestions** — Smart per-column generation strategy recommendations
- **Natural Language Config** — Describe what you want in plain text, get YAML config
- **Few-shot Examples** — Built-in example library for improved LLM output quality

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
