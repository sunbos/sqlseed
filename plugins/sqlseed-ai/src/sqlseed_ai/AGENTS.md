<!-- Parent: ../../AGENTS.md -->

# sqlseed_ai

**Generated:** 2026-06-21

## Purpose

LLM-powered schema analysis plugin for sqlseed. Analyzes database table
schemas via an OpenAI-compatible API and recommends data generation
configurations. Supports Gemma 4 native function calling, a 3-tier prompt
system (full / compact / ultra-compact), JSON-mode fallback, and automatic
model fallback on timeout/connection errors.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Plugin entry point, hook implementations, exports `plugin` |
| `analyzer/` | `SchemaAnalyzer` package — split into 5 mixin modules by concern |
| `analyzer/__init__.py` | `SchemaAnalyzer` class, composes all mixins via multiple inheritance |
| `analyzer/_caller.py` | `LLMCallerMixin` — non-streaming LLM calls, model fallback chain, kwargs building |
| `analyzer/_streaming.py` | `StreamingHandlerMixin` — streaming LLM calls, request dispatch (tool/JSON/text mode) |
| `analyzer/_tool_calling.py` | `ToolCallingMixin` — native function calling (gemma4 / openai protocols) |
| `analyzer/_context.py` | `ContextBuilderMixin` — chat message and schema context construction |
| `analyzer/_json_parser.py` | `JsonParserMixin` — JSON response parsing and analysis entry points |
| `_prompts.py` | LLM prompt templates (`SYSTEM_PROMPT`, `_COMPACT_SYSTEM_PROMPT`, `_ULTRA_COMPACT_SYSTEM_PROMPT`, `TEMPLATE_SYSTEM_PROMPT`) |
| `_tools.py` | Gemma 4 native function calling tool definitions (`GEMMA_TOOLS`) |
| `config.py` | `AIConfig`, `GemmaModel`, `AIBackend`, `ToolCallingProtocol` and resolution logic |
| `refiner.py` | `AiConfigRefiner` self-correction loop (generate → validate → fix) |
| `errors.py` | Error summarization system (`ErrorSummary` / `summarize_error()`) |
| `exceptions.py` | Structured exception types (`ContextOverflowError`, `ToolCallError`, `ModelFallbackError`, `classify_api_error()`) |
| `_client.py` | OpenAI client factory with unified httpx timeout |
| `_hardware.py` | Cross-platform hardware detection (RAM, GPU/VRAM) |
| `_json_utils.py` | LLM JSON response parsing (3-strategy fallback) |
| `_model_selector.py` | Gemma model selection and fallback chain |
| `examples.py` | Few-shot examples for LLM schema-analysis prompts |

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Change system prompt wording | `_prompts.py` | 3 tiers: `SYSTEM_PROMPT` → `_COMPACT_SYSTEM_PROMPT` → `_ULTRA_COMPACT_SYSTEM_PROMPT` |
| Modify Gemma 4 tool schema | `_tools.py` | `GEMMA_TOOLS` tuple consumed by `analyzer._try_tool_calling()` |
| Add a new backend | `config.py` | Extend `AIBackend` enum + `_resolve_backend()` + `resolve_base_url()` |
| Change model fallback order | `_model_selector.py` | `_GEMMA_MODEL_PRIORITY` tuple |
| Tune retry / refinement loop | `refiner.py` | `_refinement_loop()`, `_try_prompt_levels()` |
| Add a new error handler | `errors.py` | Append to `handlers` list in `summarize_error()` |
| Add structured exception type | `exceptions.py` | Subclass `SqlseedAIError`, add classifier logic to `classify_api_error()` |
| Change httpx timeout profile | `_client.py` | `httpx_timeout()` |
| Add few-shot examples | `examples.py` | Append to `FEW_SHOT_EXAMPLES` |
| Modify hook implementations | `__init__.py` | `sqlseed_ai_analyze_table`, `sqlseed_pre_generate_templates` |

## AIConfig Environment Variables

| Variable | Field | Fallback |
|----------|-------|----------|
| `SQLSEED_AI_API_KEY` | `api_key` | `GOOGLE_API_KEY` → `OPENAI_API_KEY` |
| `SQLSEED_AI_BASE_URL` | `base_url` | `OPENAI_BASE_URL` (auto-set per backend) |
| `SQLSEED_AI_MODEL` | `model` | None (auto-detect local models) |
| `SQLSEED_AI_TIMEOUT` | `timeout` | Default 60.0 |
| `SQLSEED_AI_BACKEND` | `backend` | Auto-detect (`google_ai_studio`, `lm_studio`, `ollama`, `openai_compat`) |
| `SQLSEED_AI_TOOL_CALLING_PROTOCOL` | `tool_calling_protocol` | `gemma4` (options: `gemma4`, `openai`, `none`) |

## 3-Tier Prompt System

Prompts live in `_prompts.py` and are selected by `analyzer.build_initial_messages()`:

1. **`SYSTEM_PROMPT`** (full) — complete instructions with generator list, rules, and output format. Used by default for cloud backends.
2. **`_COMPACT_SYSTEM_PROMPT`** (compact) — condensed generator list, single-line format. Used when context is tight or for local backends.
3. **`_ULTRA_COMPACT_SYSTEM_PROMPT`** (ultra-compact) — minimal format, no examples. Used for small local models (E2B/E4B) to minimize prefill time.

Selection precedence: `ultra_compact=True` → `compact=True` → full. Small local
models (E2B/E4B) auto-enable ultra-compact via `AIConfig.should_use_ultra_compact()`.
On context-overflow errors, `refiner._try_prompt_levels()` automatically
downgrades full → compact → ultra-compact.

`TEMPLATE_SYSTEM_PROMPT` is a separate prompt used only by
`analyzer.generate_template_values()` for the per-column value generation hook.

## LLM Call and Fallback Mechanism

1. `call_llm()` tries `response_format={"type": "json_object"}` (JSON mode) for cloud backends.
2. If the API rejects JSON mode (error contains "json"/"response_format"/"400"), falls back to plain text mode.
3. On `APITimeoutError`/`APIConnectionError`, calls `select_next_gemma_model()` to switch to the next smaller Gemma 4 model.
4. For local backends (LM Studio, Ollama), `_find_local_fallback_model()` verifies the fallback model is actually loaded before retrying.
5. At most `_MAX_FALLBACK_ATTEMPTS = 3` model downgrades are attempted.
6. If all models fail, the last exception is raised.

Gemma 4 native function calling (`_try_tool_calling()`) is attempted first
when `AIConfig.resolve_tool_calling_protocol()` returns `"gemma4"` or
`"openai"`: the model is offered `GEMMA_TOOLS` and may return a structured
`analyze_schema` invocation. The dispatch is protocol-driven (Phase E), not
backend-driven:

- `"gemma4"` (default): Gemma 4 special-token protocol; supported only on
  `GOOGLE_AI_STUDIO`.
- `"openai"`: Standard OpenAI function calling; supported on `GOOGLE_AI_STUDIO`
  and `OPENAI_COMPAT`.
- `"none"`: Skip tool calling entirely.

On backends that do not support the requested protocol, the resolver
gracefully degrades to `"none"`. On any tool-related error, the analyzer
falls back to JSON mode.

## Self-Correction Flow (AiConfigRefiner)

1. `generate_and_refine()` calls the LLM to produce a config dict.
2. The dict is validated by constructing a `TableConfig` (Pydantic model from `sqlseed.config.models`).
3. Column names are checked against the live schema via `DataOrchestrator`.
4. A 5-row preview is generated (`orch.preview_table()`) to catch runtime errors.
5. On validation failure, the error is summarized (`summarize_error()`) and fed back to the LLM as a refinement prompt.
6. At most `max_retries=3` retries. Repeated non-retryable errors (`empty_config`, `json_syntax`) terminate early after 2 occurrences.
7. Successful configs are cached on disk keyed by `_compute_schema_hash()` (first 16 chars of SHA-256 over sorted column names).

## Error Classification System (7 handlers)

`errors.summarize_error()` tries the following handlers in priority order; the
first non-None result wins:

| # | Handler | Caught Error Type |
|---|---------|-------------------|
| 1 | `_try_pydantic_error` | Pydantic `ValidationError` |
| 2 | `_try_json_error` | `JSONDecodeError` |
| 3 | `_try_attribute_generator_error` | `AttributeError` (missing `generate_*` method) |
| 4 | `_try_unknown_generator_error` | `UnknownGeneratorError` |
| 5 | `_try_expression_error` | simpleeval expression errors (incl. timeouts) |
| 6 | `_try_file_error` | `FileNotFoundError` / `PermissionError` (non-retryable) |
| 7 | `_default_error` | Catch-all; infrastructure errors marked non-retryable |

## CONVENTIONS

- **Type hints**: `from __future__ import annotations` at the top of every file.
- **Logging**: structlog via `sqlseed._utils.logger.get_logger(__name__)`.
- **Docstrings**: English, PEP 257 compliant (triple-quoted, imperative mood, Args/Returns/Raises sections).
- **Runtime validation**: use `RuntimeError`/`ValueError` (never `assert` — it can be stripped with `-O`).
- **Type safety**: never suppress type errors with `# type: ignore` or `Any` casts where a real type exists.
- **Resolution methods**: `AIConfig.resolve_*()` methods are pure functions — they return the resolved value without mutating `self`; callers must assign the return value.
- **SQL safety**: identifiers quoted via `quote_identifier()` (inherited from core sqlseed).

## ANTI-PATTERNS

- **NEVER** import `openai` at module top in `analyzer/` → use lazy init via `_client.py` (`get_openai_client()`). The top-level `from openai import OpenAI` lives only in `_client.py`, which is itself lazily imported.
- **NEVER** use `assert` for runtime validation → use `RuntimeError`/`ValueError`.
- **NEVER** suppress type errors with `# type: ignore` or `Any` where a concrete type is available.
- **NEVER** call `json.loads()` directly on LLM output → use `parse_json_response()` from `_json_utils.py` (3-strategy fallback).
- **NEVER** mutate `self` in `AIConfig.resolve_*()` methods — they are pure functions.
- **NEVER** validate AI configs with `GeneratorConfig` → use `TableConfig` (the refiner validates whole-table configs).

## For AI Agents

### Working In This Directory

- `AISqlseedPlugin` implements `hookimpl` for `sqlseed_ai_analyze_table` (full-table analysis) and `sqlseed_pre_generate_templates` (per-column value generation for non-simple columns). It does NOT implement `sqlseed_register_providers` or `sqlseed_register_column_mappers`.
- Simple columns (name, email, phone, etc.) are skipped via the `_SIMPLE_COL_RE` regex — do not waste LLM tokens on them.
- `_model_selector.py` maintains the Gemma 4 model list: `select_gemma_model()` for initial selection, `select_next_gemma_model()` for fallback.
- JSON parsing must go through `_json_utils.parse_json_response()` (3 strategies: direct → fence-strip → `raw_decode`). Never call `json.loads()` directly on LLM output.
- All AI calls must handle `APIConnectionError` / `APITimeoutError` / `APIError`.
- `refiner.py` self-correction flow: generate → validate (`TableConfig`) → fix, up to `max_retries` times.
- `config.py` `AIConfig` supports multi-backend auto-detection. Key methods: `resolve_model()`, `resolve_base_url()`, `resolve_api_key()`, `resolve_max_tokens()`, `resolve_timeout()`, `resolve_tool_calling_protocol()`, `should_use_streaming()`, `should_use_ultra_compact()`, `detect_all_local_models()`. The `tool_calling_protocol` field (Phase E) selects between `gemma4` / `openai` / `none` native function calling protocols.
- Streaming: `call_llm_streaming()` + `generate_and_refine_streaming()`. E2B/E4B models auto-disable streaming (high TTFT).
- Prompt downgrade: normal → compact → ultra-compact. Small models (E2B/E4B) auto-enable ultra-compact.

### Testing Requirements

```bash
pytest tests/test_ai_plugin.py tests/test_refiner.py
```

### Common Patterns

- Plugin registration: `ai = "sqlseed_ai:plugin"` under `[project.entry-points."sqlseed"]` in `plugins/sqlseed-ai/pyproject.toml`.
- AI call flow: `_client.py` builds client → `analyzer/_context.py` builds messages (from `_prompts.py`) → LLM call via `analyzer/_caller.py` or `analyzer/_streaming.py` (with `_tools.py` for Gemma 4) → `_json_utils.py` parses response.
- Error handling: `errors.py` `summarize_error()` converts exceptions into user-friendly `ErrorSummary` objects for LLM retry prompts.

## Dependencies

### Internal

- `sqlseed` (core, generators, plugins hookspecs, `_utils.logger`, `_utils.paths`, `config.models.TableConfig`, `core.orchestrator.DataOrchestrator`)

### External

- `openai>=1.0` — LLM API client
- `httpx>=0.24.0` — HTTP client (timeout configuration)
- `pydantic` — config and validation models (transitive via sqlseed)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
