# SQLSEED-AI PLUGIN

**Generated:** 2026-06-21

## OVERVIEW

LLM-powered schema analysis and template generation. Separate package with own pyproject.toml. Supports 4 backends (Google AI Studio, LM Studio, Ollama, OpenAI-compatible) and 5 Gemma 4 model variants.

## STRUCTURE

```
sqlseed-ai/
├── pyproject.toml        # Separate package: sqlseed>=0.1.0, openai>=1.0, httpx>=0.24.0
└── src/sqlseed_ai/
    ├── __init__.py       # AISqlseedPlugin, plugin instance, hookimpl registration
    ├── analyzer/         # SchemaAnalyzer package — split into 5 mixin modules by concern
    │   ├── __init__.py   # SchemaAnalyzer class, composes all mixins via multiple inheritance
    │   ├── _caller.py    # LLMCallerMixin — non-streaming LLM calls, model fallback chain
    │   ├── _streaming.py # StreamingHandlerMixin — streaming LLM calls, protocol-aware dispatch
    │   ├── _tool_calling.py # ToolCallingMixin — native function calling (gemma4 / openai protocols)
    │   ├── _context.py   # ContextBuilderMixin — chat message and schema context construction
    │   └── _json_parser.py # JsonParserMixin — JSON response parsing and analysis entry points
    ├── refiner.py        # AiConfigRefiner — post-generation refinement, self-correction, streaming
    ├── config.py         # AIConfig — env-based config, GemmaModel, AIBackend, ToolCallingProtocol
    ├── errors.py         # Error classification (7 processors)
    ├── exceptions.py     # Structured exception types (ContextOverflowError, ToolCallError, ModelFallbackError, classify_api_error)
    ├── _client.py        # OpenAI client wrapper, httpx timeout config
    ├── _hardware.py      # Cross-platform hardware detection (RAM, GPU/VRAM) for model selection
    ├── _model_selector.py # Gemma 4 model selection and fallback chain
    ├── _json_utils.py    # JSON parsing utilities (3-strategy fallback)
    ├── _prompts.py       # LLM prompt templates (full, compact, ultra-compact, template)
    ├── _tools.py         # Gemma 4 native function calling tool definitions (GEMMA_TOOLS)
    └── examples.py       # Few-shot examples for prompts
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add hook | `__init__.py` | Decorate with `@hookimpl` |
| Modify LLM calls | `analyzer/` | `call_llm()`, `call_llm_streaming()`, `_call_llm_once()` |
| Change model selection | `_model_selector.py` | `select_gemma_model()`, `select_next_gemma_model()` |
| Add config option | `config.py` | `AIConfig.from_env()`, `GemmaModel`, `AIBackend` |
| Modify prompt templates | `_prompts.py` | `SYSTEM_PROMPT`, `_COMPACT_SYSTEM_PROMPT`, `_ULTRA_COMPACT_SYSTEM_PROMPT` |
| Modify Gemma tools | `_tools.py` | `GEMMA_TOOLS` function declarations |
| Change error handling | `errors.py` | `summarize_error()` with 7 processors |

## CONVENTIONS

- **Entry point**: Register via `pyproject.toml` `[project.entry-points."sqlseed"]`
- **Plugin instance**: `plugin = AISqlseedPlugin()` at module level
- **Hookimpl**: Use `@hookimpl` from `sqlseed.plugins.hookspecs`
- **Error handling**: Catch `(ValueError, RuntimeError, OSError)` in hooks
- **Simple column skip**: `_SIMPLE_COL_RE` regex skips basic types

## ANTI-PATTERNS

- **NEVER** import `openai` at module top in `analyzer/` → use lazy init via `_client.py`
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

| Backend | Default Base URL | Tool Calling Protocols |
|---------|-----------------|----------------------|
| `google_ai_studio` | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemma4`, `openai` |
| `lm_studio` | `http://127.0.0.1:1234/v1` | `none` (text mode only) |
| `ollama` | `http://localhost:11434/v1` | `none` (text mode only) |
| `openai_compat` | (must set `SQLSEED_AI_BASE_URL`) | `openai` |

Tool calling protocol is selected via `AIConfig.tool_calling_protocol` (default
`"gemma4"`). `resolve_tool_calling_protocol()` narrows the choice based on what
the active backend supports (Phase E). Set `SQLSEED_AI_TOOL_CALLING_PROTOCOL`
env var to override (`gemma4`, `openai`, or `none`).
