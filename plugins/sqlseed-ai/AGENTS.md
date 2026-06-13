# SQLSEED-AI PLUGIN

## OVERVIEW

LLM-powered schema analysis and template generation. Separate package with own pyproject.toml. Supports 4 backends (Google AI Studio, LM Studio, Ollama, OpenAI-compatible) and 5 Gemma 4 model variants.

## STRUCTURE

```
sqlseed-ai/
├── pyproject.toml        # Separate package: sqlseed>=0.1.0, openai>=1.0
└── src/sqlseed_ai/
    ├── __init__.py       # AISqlseedPlugin, plugin instance, hookimpl registration
    ├── analyzer.py       # SchemaAnalyzer — LLM schema analysis, streaming, tool calling
    ├── refiner.py        # AiConfigRefiner — post-generation refinement, self-correction, streaming
    ├── config.py         # AIConfig — env-based config, GemmaModel enum, AIBackend enum
    ├── errors.py         # Error classification (7 processors)
    ├── _client.py        # OpenAI client wrapper, httpx timeout config
    ├── _model_selector.py # Gemma 4 model selection and fallback chain
    ├── _json_utils.py    # JSON parsing utilities (3-strategy fallback)
    └── examples.py       # Few-shot examples for prompts
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add hook | `__init__.py` | Decorate with `@hookimpl` |
| Modify LLM calls | `analyzer.py` | `call_llm()`, `call_llm_streaming()`, `_call_llm_once()` |
| Change model selection | `_model_selector.py` | `select_gemma_model()`, `select_next_gemma_model()` |
| Add config option | `config.py` | `AIConfig.from_env()`, `GemmaModel`, `AIBackend` |
| Modify prompt templates | `analyzer.py` | `_SYSTEM_PROMPT`, `_COMPACT_SYSTEM_PROMPT`, `_ULTRA_COMPACT_SYSTEM_PROMPT` |
| Change error handling | `errors.py` | `summarize_error()` with 7 processors |

## CONVENTIONS

- **Entry point**: Register via `pyproject.toml` `[project.entry-points."sqlseed"]`
- **Plugin instance**: `plugin = AISqlseedPlugin()` at module level
- **Hookimpl**: Use `@hookimpl` from `sqlseed.plugins.hookspecs`
- **Error handling**: Catch `(ValueError, RuntimeError, OSError)` in hooks
- **Simple column skip**: `_SIMPLE_COL_RE` regex skips basic types

## ANTI-PATTERNS

- **NEVER** import openai at module top → use lazy init in `_get_analyzer()`
- **NEVER** raise from hook methods → return None on failure
- **ALWAYS** use `AIConfig.from_env()` for configuration
- **ALWAYS** cap template generation at 50 values (`min(count, 50)`)

## Gemma 4 Model Variants

| Enum | Model ID | Use Case |
|------|----------|----------|
| `GEMMA_4_E2B` | `gemma-4-e2b-it` | Ultra-light edge, Ollama/LM Studio |
| `GEMMA_4_E4B` | `gemma-4-e4b-it` | Lightweight local, LM Studio |
| `GEMMA_4_12B` | `gemma-4-12b-it` | Balanced, LM Studio/Ollama |
| `GEMMA_4_26B_A4B` | `gemma-4-26b-a4b-it` | High quality, recommended |
| `GEMMA_4_31B` | `gemma-4-31b-it` | Best quality, Google AI Studio |

## Backend Configuration

| Backend | Default Base URL | Notes |
|---------|-----------------|-------|
| `google_ai_studio` | `https://generativelanguage.googleapis.com/v1beta/openai/` | Cloud, supports tool calling |
| `lm_studio` | `http://127.0.0.1:1234/v1` | Local, auto-detect models |
| `ollama` | `http://localhost:11434/v1` | Local, offline |
| `openai_compat` | (must set `SQLSEED_AI_BASE_URL`) | Generic OpenAI-compatible |
