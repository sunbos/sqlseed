# SQLSEED-AI PLUGIN

**Last updated:** 2026-07-12

## OVERVIEW

LLM-powered schema analysis, contract-driven self-healing, and template generation. Separate package with own pyproject.toml. Supports 4 backends (Google AI Studio, LM Studio, Ollama, OpenAI-compatible) and 5 Gemma 4 model variants.

The default schema-analysis path is the **v4 contract-driven self-healing architecture** (Layers 1–5 below). The legacy `Stage3Validator` (36 numbered rules), `SchemaSemanticAnalyzer`, and `StagedSchemaAnalyzer` were **deleted** in Phase 4 zero-rot cleanup — there is no dual-track system and no deprecated flags. See [CLAUDE.md → "v4 Contract-Driven Self-Healing"](../../CLAUDE.md) for the authoritative, exhaustive reference (including all 62 cross-column patterns).

## STRUCTURE

```
sqlseed-ai/
├── pyproject.toml        # Separate package: sqlseed>=0.1.0, openai>=1.0, httpx>=0.24.0
└── src/sqlseed_ai/
    ├── __init__.py       # AISqlseedPlugin, plugin instance, hookimpl registration
    ├── analyzer/         # Layer 6 — SchemaAnalyzer (table-level LLM analysis), split into 5 mixin modules
    │   ├── __init__.py   # SchemaAnalyzer class, composes all mixins via multiple inheritance
    │   ├── _caller.py    # LLMCallerMixin — non-streaming LLM calls, model fallback chain
    │   ├── _streaming.py # StreamingHandlerMixin — streaming LLM calls, protocol-aware dispatch
    │   ├── _tool_calling.py # ToolCallingMixin — native function calling (gemma4 / openai protocols)
    │   ├── _context.py   # ContextBuilderMixin — chat message and schema context construction
    │   └── _json_parser.py # JsonParserMixin — JSON response parsing and analysis entry points
    ├── contracts/        # Layer 1 — sparse contract matrix + resolver (known-bad generator/type/constraint combos)
    │   ├── registry.py   # LearnedContractsRegistry (JSON-persisted learned contracts, schema_hash filtered)
    │   ├── builtin_violations.py  # seed violations; matrix is a CLOSED SET (unlisted → COMPATIBLE)
    │   └── matrix.py     # ContractViolation, ContractResolver, ViolationKind (specificity-priority matching)
    ├── validator/        # Layer 2 — FastValidator orchestrating 5 components
    │   ├── main.py       # FastValidator: SingleColumnValidator(2a), CrossColumnValidator(2b), DialectErrorParser, ShadowFKScanner, CompositeFKCoordinator
    │   ├── single_column.py   # per-column contract + cardinality
    │   ├── cross_column.py    # FK integrity + derive_from DAG cycle detection
    │   ├── dialect_parser.py  # Defense 3: normalize DBAPI exceptions → ViolationReport
    │   ├── shadow_fk_scan.py  # Section 14.3: localize SQLite FK violation column
    │   ├── composite_fk.py    # multi-column FK
    │   ├── schema_snapshot.py # schema_hash for optimistic-lock re-check at write time (Defense 8)
    │   └── models.py    # ConstraintType, ViolationReport, ValidationResult
    ├── repair/           # Layer 3 — stateless repair engine (pure functions registered in REPAIR_STRATEGIES)
    │   ├── strategies.py # normalize_params (Rule #14), coerce_float_to_int (Rule #26), derive_from cleanup, CHECK-chain mirroring
    │   ├── executor.py   # applies strategies by fix_hint dispatch
    │   └── pipeline.py   # chains strategies
    ├── healer/           # Layer 4 — 4-level LLM heal with failure-type-aware routing
    │   ├── orchestrator.py        # HealOrchestrator: Level1(subgraph)→Level2(column)→Level3(compact)→Level4(degrade)
    │   ├── level1_subgraph_healer.py  # sends entire subgraph (default)
    │   ├── level2_column_healer.py    # sends target col + dependency set (context-overflow path)
    │   ├── level3_compact_healer.py   # compact/ultra-compact prompts + JSON repair
    │   ├── degrader.py    # ProgressiveDegrader — deterministic fallback (Level 4)
    │   ├── context_detector.py  # ContextWindowDetector — skip Level1 if tokens > 60% of context window
    │   ├── failure_classifier.py  # 6 failure types: CONTEXT_OVERFLOW/EMPTY_RESPONSE/JSON_FORMAT/SEMANTIC/NETWORK/UNKNOWN
    │   ├── oscillation.py, subgraph.py (Tarjan SCC + megacluster breaking), post_repair.py (BrokenEdgeAligner), diff_learner.py, _client.py
    │   └── models.py
    ├── auto_heal/        # Layer 5 — top-level entry: AutoHealOrchestrator (ai-analyze default path)
    │   ├── orchestrator.py  # SchemaSnapshot→SubgraphSplitter→per-subgraph(L2 validate→L3 repair→L4 heal)→BrokenEdgeAligner→schema_hash re-check→emit YAML
    │   └── time_budget.py  # TimeBudgetController — wall-clock budget
    ├── refiner.py        # AiConfigRefiner — self-correction loop; delegates Rule #14 to Layer 3 normalize_params
    ├── ai_mediator.py    # AI-specific mediation — apply_ai_suggestions() (Phase C moved from core)
    ├── config.py         # AIConfig — env-based config, GemmaModel, AIBackend, ToolCallingProtocol (use_staged_pipeline removed)
    ├── errors.py         # Error classification (7 processors)
    ├── exceptions.py     # Structured exception types (ContextOverflowError, ToolCallError, ModelFallbackError, classify_api_error)
    ├── _client.py        # OpenAI client wrapper, httpx timeout config
    ├── _hardware.py      # Cross-platform hardware detection (RAM, GPU/VRAM) for model selection
    ├── _model_selector.py # Gemma 4 model selection and fallback chain
    ├── _json_utils.py    # JSON parsing utilities (4-strategy fallback)
    ├── _prompts.py       # LLM prompt templates (full, compact, ultra-compact, template)
    ├── _tools.py         # Gemma 4 native function calling tool definitions (GEMMA_TOOLS)
    ├── examples.py       # Few-shot examples for prompts
    ├── cli/ai_commands.py # 3 commands injected into sqlseed CLI: ai-suggest, ai-analyze, auto-heal
    └── mcp.py            # AI MCP server (sqlseed_ai_generate_yaml, sqlseed_gemma4_analyze, sqlseed_gemma4_agent_fill, sqlseed_list_gemma_models)
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
| Add/edit a cross-column CHECK pattern | `auto_heal/orchestrator.py` `_infer_cross_column_config()` | Patterns 1–46 (62 total, incl. letter-suffix variants 1b/4a/7a/7b/8a–8e/22b/22c/24b/26b/26c/28b/28c/30b/34b); read CLAUDE.md first — many are interdependent (pre-loop scans, ordering rules) |
| Add a known-bad generator/type combo | `contracts/builtin_violations.py` | Matrix is a CLOSED SET; unlisted → COMPATIBLE |
| Add a repair strategy | `repair/strategies.py` | Register pure fn in `REPAIR_STRATEGIES` keyed by `fix_hint` |
| Change LLM heal routing | `healer/failure_classifier.py` + `healer/orchestrator.py` | 6 failure types route to Levels 2/3/4 or raise |
| Change top-level heal pipeline | `auto_heal/orchestrator.py` `AutoHealOrchestrator.run()` | Includes Step 5.5 post-LLM safety nets |

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
