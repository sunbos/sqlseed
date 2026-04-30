# SQLSEED-AI PLUGIN

## OVERVIEW

LLM-powered schema analysis and template generation. Separate package with own pyproject.toml.

## STRUCTURE

```
sqlseed-ai/
├── pyproject.toml        # Separate package: sqlseed>=0.1.0, openai>=1.0
└── src/sqlseed_ai/
    ├── __init__.py       # AISqlseedPlugin, plugin instance, hookimpl registration
    ├── provider.py       # AIProvider — stub generator (returns defaults)
    ├── analyzer.py       # SchemaAnalyzer — LLM schema analysis
    ├── refiner.py        # Refiner — post-generation refinement
    ├── config.py         # AIConfig — env-based OpenAI config
    ├── errors.py         # Custom exceptions
    ├── _client.py        # OpenAI client wrapper
    ├── _model_selector.py # Model selection logic
    ├── _json_utils.py    # JSON parsing utilities
    └── examples.py       # Usage examples
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add hook | `__init__.py` | Decorate with `@hookimpl` |
| Modify LLM calls | `_client.py` | OpenAI client wrapper |
| Change model selection | `_model_selector.py` | Model picker logic |
| Add config option | `config.py` | AIConfig.from_env() |

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
