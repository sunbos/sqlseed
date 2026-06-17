# Gemma 4 Integration Guide

GemmaSQLSeed deeply integrates with the Gemma 4 model family, leveraging **Native Function Calling** for intelligent schema analysis and data generation.

## Supported Models

| Model | Variant | Recommended Backend | Use Case |
|-------|---------|-------------------|----------|
| `gemma-4-e2b-it` | E2B (2B Effective, Edge) | Ollama / LM Studio | Ultra-light edge deployment |
| `gemma-4-e4b-it` | E4B (4B Effective, Edge) | LM Studio | Local schema analysis |
| `gemma-4-12b-it` | 12B Unified | LM Studio / Ollama | Balanced quality and speed |
| `gemma-4-26b-a4b-it` | 26B A4B MoE | Google AI Studio | Complex analysis + self-correction |
| `gemma-4-31b-it` | 31B Dense | Google AI Studio | Maximum reasoning capability |

## Backend Configuration

### Google AI Studio (Cloud)

```bash
export GOOGLE_API_KEY=your-key
# Model defaults to gemma-4-26b-a4b-it
```

### LM Studio (Local GUI)

```bash
export SQLSEED_AI_BACKEND=lm_studio
export SQLSEED_AI_MODEL=google/gemma-4-e4b
# Ensure LM Studio is running with a Gemma 4 model loaded
```

### Ollama (Local CLI)

```bash
export SQLSEED_AI_BACKEND=ollama
export SQLSEED_AI_MODEL=gemma-4-e4b-it
# Ensure Ollama is running: ollama pull gemma4:4b
```

## Native Function Calling

GemmaSQLSeed defines two function interfaces via `GEMMA_TOOLS`:

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
                },
                "required": ["table_name", "columns"],
            },
        },
    }
]
```

### generate_column_values

Generates realistic sample values for a specific database column.

### Calling Flow

```
1. Send tools=GEMMA_TOOLS, tool_choice="auto" to Gemma 4
2. Gemma 4 selects analyze_schema function, returns structured parameters
3. Extract JSON from tool_call.function.arguments
4. Fallback chain: Tool Calling -> JSON mode -> Plain text
```

## Agent Memory (Self-Correction)

The `AiConfigRefiner` implements a self-correction loop:

```
Gemma 4 generates initial config
    -> Validate (type check, constraint check, dependency integrity)
    -> If errors found:
        -> Feed error messages back to Gemma 4
        -> Gemma 4 corrects the config
        -> Re-validate (up to 3 rounds)
    -> Final config -> Data fill
```

## MCP Server Tools

Three Gemma 4-specific MCP tools are available:

| Tool | Description |
|------|-------------|
| `sqlseed_gemma4_analyze` | Analyze schema using Gemma 4 with Native Function Calling |
| `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow (analyze -> config -> fill) |
| `sqlseed_list_gemma_models` | List available Gemma 4 models and backend status |

## Quick Start

```bash
# One-click setup with Gemma 4
python scripts/quickstart.py --backend lm_studio --model google/gemma-4-e4b

# CLI usage
sqlseed ai-suggest app.db -t users -o config.yaml

# Python API
from sqlseed_ai import SchemaAnalyzer
from sqlseed_ai.config import AIConfig

config = AIConfig.from_env()  # Reads SQLSEED_AI_BACKEND, SQLSEED_AI_MODEL
analyzer = SchemaAnalyzer(config=config)
result = analyzer.analyze_table_from_ctx(db_path="app.db", table_name="users")
```

## Performance Reference

| Backend | Model | Schema Analysis Time | Notes |
|---------|-------|---------------------|-------|
| LM Studio | E4B (4B Effective, Edge) | ~5 min | Local inference, full system prompt |
| LM Studio | E4B (4B Effective, Edge) (compact) | ~20s | Reduced prompt, fewer examples |
| Google AI Studio | 26B A4B MoE | ~10-30s | Cloud inference, recommended |
| Ollama | 4B | ~3-5 min | Local CLI, similar to LM Studio |
