# PROJECT KNOWLEDGE BASE

**Last updated:** 2026-08-30
**Branch:** `feat/contract-driven-self-healing`

## OVERVIEW

Declarative Multi-Database test data generation toolkit. YAML/JSON config or Python API. Auto-infers schema, 9-level column mapping, 35 generators, plugin system (pluggy). Supports SQLite (default) and PostgreSQL via SQLAlchemy. MySQL removed (deferred until PostgreSQL fully validated). Gemma 4 as long-term LLM backend (protocol-based native function calling). License: **AGPL-3.0-or-later**.

**Stack**: Python 3.10+ (`requires-python = ">=3.10"`), hatchling + hatch-vcs build, ruff lint, mypy strict, pytest. CI also gates on `lint-imports` (architectural layer contracts); `mutmut` (mutation testing) is a local pre-merge gate via `make mutmut` — too slow for push CI.

**Architecture**: 5 independent packages — `sqlseed` (core, offline), `sqlseed-cli` (CLI plugin), `sqlseed-ai` (AI plugin), `mcp-server-sqlseed` (MCP plugin; module path is `mcp_server_sqlseed`, note the underscore), `sqlseed-ui` (web UI plugin: FastAPI + dependency-free static frontend; optional `[ai]` extra for the heal lab). See [ARCHITECTURE.md](./ARCHITECTURE.md) for the authoritative architecture reference; [CLAUDE.md](./CLAUDE.md) has the canonical "Never/Always" rules.

**Current work**: the `sqlseed-ai` self-healing subsystem (`auto_heal/`, `healer/`, `validator/`, `repair/`, `contracts/`) — contract-driven, multi-level repair pipeline.

## STRUCTURE

```
sqlseed/
├── src/sqlseed/          # Core package (no CLI/AI/MCP code)
│   ├── __init__.py       # Public API: fill, connect, fill_from_config, preview
│   ├── core/             # Orchestrator, mapper, schema, CHECK parse/adapt, constraints, DAG, enrichment, transform
│   ├── generators/       # Data providers: base, faker, mimesis
│   ├── database/         # DB adapters: SQLAlchemy (required, SQLite+PostgreSQL), raw sqlite3 (test-only)
│   ├── plugins/          # Plugin infrastructure: hookspecs, manager, mediator
│   ├── config/           # Pydantic models, YAML loader, snapshots
│   └── _utils/           # Internal: sql_safe, metrics, progress, logger, paths
├── tests/                # Core pytest suite, conftest fixtures
├── plugins/
│   ├── sqlseed-cli/      # CLI plugin: fill, preview, inspect, init, replay (separate package)
│   ├── sqlseed-ai/       # AI plugin: LLM schema analysis + self-healing (healer/, validator/, repair/, contracts/)
│   ├── sqlseed-ui/       # Web UI plugin: FastAPI + static frontend (schema/mapping/preview/fill/heal lab)
│   └── mcp-server-sqlseed/  # MCP server: rule-driven YAML gen + execute_fill (no LLM)
├── scripts/              # Helper scripts (run scripts, validation harnesses)
├── docs/                 # mkdocs-material site
└── examples/             # Usage examples
```

## MODULE-LEVEL AGENTS.md

The repo ships 23 `AGENTS.md` files (1 root + 22 nested), one per package/test subdir. **Before editing a module, read the nearest `AGENTS.md`** for that area's local conventions and gotchas:

```
src/sqlseed/AGENTS.md                      (core package root)
src/sqlseed/core/AGENTS.md                 (orchestrator, mapper, schema, relation, ...)
src/sqlseed/config/AGENTS.md
src/sqlseed/database/AGENTS.md
src/sqlseed/generators/AGENTS.md
src/sqlseed/plugins/AGENTS.md              (plugin infrastructure: hookspecs + manager)
src/sqlseed/_utils/AGENTS.md
plugins/sqlseed-cli/AGENTS.md
plugins/sqlseed-cli/src/sqlseed_cli/AGENTS.md
plugins/sqlseed-ai/AGENTS.md
plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md
plugins/sqlseed-ui/AGENTS.md
plugins/mcp-server-sqlseed/AGENTS.md
plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/AGENTS.md
tests/AGENTS.md + tests/{test_core,test_config,test_database,test_generators,test_plugins,test_utils,benchmarks}/AGENTS.md
```

This root file is the index; module-level files carry the detail. When adding a new package subdir, create its `AGENTS.md` too.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new generator | `src/sqlseed/generators/` | Create new provider; base_provider is type-routing only, real data from faker/mimesis |
| Modify column mapping | `src/sqlseed/core/mapper.py` | 9-level strategy chain |
| Edit orchestrator | `src/sqlseed/core/orchestrator/` | Package of 4 mixins + `_common` (see ORCHESTRATOR PACKAGE LAYOUT below) |
| Add CLI command | `plugins/sqlseed-cli/src/sqlseed_cli/main.py` | Core commands (fill, preview, inspect, init, replay) |
| Add AI CLI command | `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` | 3 AI commands (ai-suggest, ai-analyze, auto-heal), injected via entry_points |
| Add plugin hook | `src/sqlseed/plugins/hookspecs.py` | pluggy hookspec |
| Modify schema inference | `src/sqlseed/core/schema.py` | SchemaInferrer class |
| Change batch insert | `src/sqlseed/database/` | SQLAlchemyAdapter (required), RawSQLiteAdapter (test-only) |
| Add test fixture | `conftest.py` (repo root) | tmp_db, tmp_db_with_data, unique_test_db (auto-discovered by all tests) |
| Configure AI plugin | `plugins/sqlseed-ai/` | Separate pyproject.toml, Gemma 4 multi-backend, `tool_calling_protocol` field |
| Add MCP tool | `plugins/mcp-server-sqlseed/` | FastMCP, 2 tools (generate_yaml rule-driven, execute_fill). AI tools in sqlseed-ai[mcp] |
| Run web UI | `plugins/sqlseed-ui/` | `sqlseed-ui` → http://127.0.0.1:8630 (FastAPI + static frontend; heal lab needs sqlseed-ai[ai]) |

## PUBLIC API (`src/sqlseed/__init__.py`)

| Function | Purpose |
|----------|---------|
| `fill(db_path, *, url, table, count, ...)` | Single-table zero-config fill |
| `connect(db_path, *, url, ...)` | Returns `DataOrchestrator` context manager |
| `preview(db_path, *, url, table, count, ...)` | Preview data without writing |
| `fill_from_config(config_path)` | Batch fill from YAML/JSON config |
| `load_config(path)` | Load config as `GeneratorConfig` |

The connection-taking public API functions (`fill`, `connect`, `preview`) accept `db_path` (SQLite file) and `url` (database URL) as **mutually exclusive** connection modes — never pass both. `fill_from_config` takes a `config_path` and `load_config` takes a `path`, so they do not take connection args.

## ORCHESTRATOR PACKAGE LAYOUT

`core/orchestrator/` is a **package**, not a single file. `DataOrchestrator` is composed via multiple inheritance from 4 mixins + 1 shared data module:

- `_common.py` — Shared dataclasses (not a mixin): `CoreCtx` (db, schema, mapper, relation, shared_pool), `ExtCtx` (registry, plugins, plugin_mediator, enrichment, unique_adjuster, schema_fallback, metrics). Helper: `_is_db_url()`.
- `_connection.py` — `ConnectionMixin`: lifecycle (`__init__`, `_ensure_connected`, `close`), adapter creation, property accessors, context manager protocol, `from_config()` classmethod.
- `_specs.py` — `SpecResolverMixin`: `_resolve_specs()` (schema inference → CHECK adaptation (`CheckAdapter`, clamps user params to single-column CHECK bounds BEFORE mapping) → column mapping → enrichment → unique adjustment → FK resolution), `_build_stream()` (also extracts cross-column comparison CHECK constraints `col1 OP col2` into `inequality_constraints`), `_prepare_specs()`, `_resolve_user_configs()`.
- `_generation.py` — `GenerationMixin`: `_generate_and_insert_batches()`, `fill_table()` (main entry point), `preview_table()`. (`fill = fill_table` alias.)
- `_query.py` — `QueryMixin`: `get_schema_context()`, `get_column_mapping()`, `get_column_names()`, `get_skippable_columns()`, `get_topological_table_order()`, `get_table_names()`, `get_column_info()`, `get_foreign_keys()`, `get_row_count()`, `execute()`, `query()`, `fetch_one()`, `report()`, `map_column()`.

Import as `from sqlseed.core.orchestrator import DataOrchestrator`. When editing, put changes in the correct mixin — don't add lifecycle code to the generation mixin, etc.

## CONFIG MODEL INVARIANTS

`GeneratorConfig` → `list[TableConfig]` → `list[ColumnConfig]` + `list[ColumnAssociation]`. Enforced by Pydantic `model_validator`:

- `GeneratorConfig.db_path` and `url` are **mutually exclusive**. `connection_target` property returns whichever is set.
- `ColumnConfig` has two **mutually exclusive** modes:
  - **Source mode**: `generator` + `params` + `null_ratio` + `provider`
  - **Derived mode**: `derive_from` + `expression`
- `ColumnConfig.constraints: ColumnConstraintsConfig` (unique, min_value, max_value, regex, max_retries with `ge=0`).
- `ColumnConfig` also supports `faker_method`, `mimesis_method`, `native_params` for AI-suggested native method overrides.

## CONVENTIONS

- **Type hints**: `from __future__ import annotations` at top of every file
- **Logging**: structlog via `sqlseed._utils.logger.get_logger(__name__)`
- **SQL safety**: Always use `quote_identifier()` from `_utils/sql_safe.py`
- **Test naming**: `test_<module>.py` mirrors `src/sqlseed/<module>/`
- **Provider pattern**: Implement `DataProvider` protocol (no base class required)
- **Entry points**: Register providers via `pyproject.toml` `[project.entry-points."sqlseed"]`

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER** use raw string formatting for SQL identifiers → use `quote_identifier()`
- **NEVER** import third-party libs without try/except in provider files (optional deps only; faker is required)
- **NEVER** suppress type errors with `as any` or `@ts-ignore`
- **NEVER** use `assert` for runtime validation → use `RuntimeError`/`ValueError` (asserts can be optimized away with `-O`)
- **NEVER** let `sqlseed.generators` or `sqlseed.database` import `sqlseed.core` (enforced by `lint-imports` — CI gate)
- **NEVER** let `sqlseed._utils` import any upper layer (`core`/`generators`/`database`/`plugins`/`config`) — `_utils` is the leaf layer (enforced by `lint-imports`)
- **ALWAYS** use `from __future__ import annotations` (enforced by ruff)
- **ALWAYS** use SQLAlchemyAdapter for multi-DB support; RawSQLiteAdapter for zero-dep tests

## PLUGIN HOOKS (12 total)

Defined in `src/sqlseed/plugins/hookspecs.py`. `firstresult=✓` means pluggy returns the first non-None result; otherwise returns `list[result]`.

| Hook | firstresult | Trigger |
|------|:-----------:|---------|
| `sqlseed_register_providers(registry)` | ✗ | `_ensure_connected()` |
| `sqlseed_register_column_mappers(mapper)` | ✗ | `_ensure_connected()` |
| `sqlseed_ai_analyze_table(...)` | ✓ | Low-level LLM call |
| `sqlseed_apply_ai_suggestions(...)` | ✓ | Orchestrator `_resolve_specs()` (implemented in `sqlseed_ai.ai_mediator`) |
| `sqlseed_before_generate(table_name, count, config)` | ✗ | Before main generation loop |
| `sqlseed_after_generate(table_name, count, elapsed)` | ✗ | After generation completes |
| `sqlseed_transform_row(table_name, row)` | ✗ | Per-row (hot path — mind performance) |
| `sqlseed_transform_batch(table_name, batch)` | ✗ | `apply_batch_transforms()` |
| `sqlseed_before_insert(table_name, batch_number, batch_size)` | ✗ | Before each batch write |
| `sqlseed_after_insert(table_name, batch_number, rows_inserted)` | ✗ | After each batch write |
| `sqlseed_shared_pool_loaded(table_name, shared_pool)` | ✗ | After `register_shared_pool()` |
| `sqlseed_pre_generate_templates(...)` | ✓ | `apply_template_pool()` |

**Gotcha**: pluggy returns `list[result]` for non-firstresult hooks, not a single value. Batch transforms chain: last non-`None` result wins (not accumulative).

## CI GATES (must pass before merge)

- `ruff check src/ tests/ plugins/` and `ruff format --check src/ tests/ plugins/`
- `mypy src/sqlseed/ plugins/` (strict on source; tests excluded)
- `pytest`
- `lint-imports` — enforces the 3 forbidden layer contracts in `pyproject.toml` `[tool.importlinter]`: generators/database must not import core; `_utils` must not import upper layers. Violations fail CI automatically instead of relying on agents reading docs.
- `tests/test_architecture.py` — 14 invariant tests complementing `lint-imports`: module location, count contracts (generator/hook/exact-rule counts), public API surface, production isolation. All must pass before merge.
- `pytest tests/test_doc_sync.py` — verifies AUTO-GENERATED count markers in docs match the code. Run after editing `mapper.py` / `_dispatch.py` / `hookspecs.py` / `models.py` / `__init__.py` (see DOC SYNC RULES below).
- `mutmut` — mutation testing to catch self-proving mock-based tests (local gate: run `make mutmut` before merge; NOT executed in push CI due to runtime cost). **Windows gotcha**: mutmut 3.x is not Windows-native; use `mutmut<3` and set `PYTHONUTF8=1` (see `Makefile` `mutmut` target). Default high-risk module is `unique_adjuster`; override with `--paths-to-mutate`. Baseline: 49.2% survival on 2026-06-25 — surviving mutants indicate self-proving tests. `make mutmut-report` shows survivor IDs (`python -m mutmut show <id>` to inspect); `make mutmut-clean` resets the cache.

## UNIQUE STYLES

- **Provider fallback chain**: mimesis (optional, high-performance) → faker (required, standard) → base (type-routing only, no real data)
- **AI backend fallback chain**: Google AI Studio → LM Studio → Ollama → OpenAI-compat (4 backends, no gemma4 backend)
- **Gemma 4 protocol-based tool calling**: `AIConfig.tool_calling_protocol: Literal["gemma4", "openai", "none"]` (Phase E of ARCHITECTURE.md §8 refactoring). `GEMMA_TOOLS` shared across protocols; `resolve_tool_calling_protocol()` narrows based on backend support. Gemma4 is a long-term LLM backend (NOT competition-only).
- **Context manager pattern**: `DataOrchestrator` is a context manager
- **Plugin mediation**: `PluginMediator` bridges plugins and core (generic methods only: `apply_batch_transforms`, `apply_template_pool`). AI-specific `apply_ai_suggestions` moved to `sqlseed-ai` (Phase C of ARCHITECTURE.md §8 refactoring), invoked via pluggy hook.
- **DAG-based column ordering**: `ColumnDAG` handles derive_from dependencies
- **SnapshotManager**: save/load/list_snapshots only; CLI `replay` uses load() + DataOrchestrator.from_config()

## CRITICAL PITFALLS

Battle scars — read before touching the relevant areas:

1. **Seed handling**: Don't set provider seed in the orchestrator — `DataStream.__init__` does it (`set_seed` only when `seed is not None`).
2. **Hook return values**: pluggy returns `list[result]` for non-firstresult hooks, not a single value.
3. **Mimesis locale**: Use short codes (`"en"`, `"zh"`) — NOT Faker-style (`"en_US"`, `"zh_CN"`).
4. **Memory**: Never collect all rows before writing — use the `DataStream.generate()` iterator (streaming).
5. **Expression timeout**: Always handle `ExpressionTimeoutError`; timeout threads can't be killed (5s default via `simpleeval`).
6. **Batch transforms chain**: Last non-`None` result wins — not accumulative.
7. **PRAGMA restore**: Must be in a `finally` block, or the DB stays in an unsafe state.
8. **SQLAlchemy is the required adapter**: `database/sqlalchemy_adapter.py` is required; `RawSQLiteAdapter` is test-only fallback.
9. **Provider fallback**: `_ensure_connected()` silently falls back to `"base"` on provider load failure. Chain: mimesis (optional) → faker (required) → base (type-routing only, no real data).
10. **Orchestrator is a package**: `core/orchestrator/` is 4 mixins + `_common` (see ORCHESTRATOR PACKAGE LAYOUT). Import as `from sqlseed.core.orchestrator import DataOrchestrator`.
11. **db_path vs url**: Mutually exclusive on both public API and CLI. Never pass both.
12. **AUTO-GENERATED markers**: Doc files use `<!-- BEGIN:AUTO-GENERATED:name -->value<!-- END:AUTO-GENERATED:name -->`. Don't manually edit values inside markers — run `scripts/sync_docs.py` and `pytest tests/test_doc_sync.py`.
13. **Mock self-proving trap**: Tests that mock `sqlseed.core.*` / `generators.*` / `database.*` classes (e.g., `mapper.map_column = MagicMock(return_value=...)` then `assert_called_once_with(...)`) are self-proving — the assertion echoes the mock setup and never verifies the computed `GeneratorSpec.params`. Use a real `ColumnMapper` + real `ColumnInfo` with non-None `default` and a non-exact-match column name (e.g., `"category"`/`"rank"`) to exercise `_type_faithful_fallback` and downstream `_adjust_*` math. See `tests/test_core/test_unique_adjuster.py::TestAdjustChoiceFallback` for the recommended pattern. Run `make mutmut` to detect self-proving tests.
14. **Architecture enforcement is multi-layer**: 4 complementary mechanisms — (a) `lint-imports` (CI gate, fails fast on forbidden layer crossings), (b) `tests/test_architecture.py` (14 invariant tests), (c) `make mutmut` (mutation testing), (d) `tests/test_doc_sync.py` (count markers match code). All 4 must pass before merge.
15. **CHECK adaptation is deterministic-only**: `check_adapt.py` clamps user params to single-column literal CHECK bounds (overlap → clamp + notice; disjoint → `ConfigurationError`). Cross-column/OR/unparseable CHECKs stay the AI/manual domain — never "guess" them in core. Composite PRIMARY KEYs are treated as composite UNIQUE constraints (`unique_adjuster.detect_unique_columns()`), not per-column unique.

## AI SELF-HEALING SUBSYSTEM (`sqlseed-ai`, current branch focus)

The `feat/contract-driven-self-healing` branch adds a contract-driven, multi-level repair pipeline under `plugins/sqlseed-ai/src/sqlseed_ai/`. The v4 architecture is a 6-layer pipeline built on the open-closed principle: core code (Registry + Validator + Executor) is closed; rules are open for extension via the `REPAIR_STRATEGIES` dict. Layer numbers are the canonical vocabulary used in docs/commits — grep for them.

- **Layer 1 — `contracts/`** — Sparse contract matrix + resolver. `ContractViolation` defines a single bad generator/type/constraints combination; `ContractResolver` merges builtin + learned violations with specificity-priority matching. The matrix is a *closed set* — only known-bad combinations are listed; unlisted combinations default to COMPATIBLE. `builtin_violations.py` ships the seed violations; `registry.py` exposes the lookup API.
- **Layer 2 — `validator/`** — `FastValidator` orchestrates five components: `single_column` (per-column contract + cardinality), `cross_column` (FK integrity + derive_from DAG cycle detection), `composite_fk`, `shadow_fk_scan` (localize SQLite FK violation column), `dialect_parser` (normalize DBAPI exceptions to `ViolationReport`). `schema_snapshot.py` records `schema_hash` at startup for optimistic-lock re-check at write time.
- **Layer 3 — `repair/`** — Stateless repair engine. Each strategy is a pure function `RepairFn = Callable[[dict, ViolationReport, dict], dict]` registered in `REPAIR_STRATEGIES`. `strategies.py` ships canonical strategies — notably `normalize_params` (strips params not in `_GENERATOR_PARAM_WHITELIST` for ALL generators), `coerce_float_to_int` (`random_float` → `random_int` for INTEGER columns), plus derive_from cleanup, date-column generator fixes, CHECK-chain mirroring. `executor.py` applies strategies by `fix_hint` dispatch; `pipeline.py` chains them.
- **Layer 4 — `healer/`** — 4-level LLM heal architecture with failure-type-aware routing. `orchestrator.py` (`HealOrchestrator`) coordinates: Level 1 (subgraph) → Level 2 (column) → Level 3 (compact) → Level 4 (deterministic degrade). Supporting: `failure_classifier` (6 types: `CONTEXT_OVERFLOW`/`EMPTY_RESPONSE`/`JSON_FORMAT`/`SEMANTIC`/`NETWORK`/`UNKNOWN`), `oscillation`, `degrader` (semantic downgrade safety net), `post_repair` (broken FK edge aligner), `diff_learner` (persists learned violations back to Layer 1), `subgraph` (Tarjan SCC + megacluster breaking), `context_detector` (dynamic context-window detection, skips Level 1 if token estimate > 60% of window). Routing: `CONTEXT_OVERFLOW`/`EMPTY_RESPONSE` → Level 2; `JSON_FORMAT` → Level 3; `SEMANTIC` → Level 4; `NETWORK` → raise.
- **Layer 5 — `auto_heal/`** — `AutoHealOrchestrator` (`orchestrator.py`) is the top-level entry point for `ai-analyze` (default v4 path), `ai-suggest --auto-heal`, and the standalone `auto-heal` command. Pipeline: SchemaSnapshot → SubgraphSplitter → per-subgraph (Layer 2 validate → Layer 3 repair → Layer 4 heal) → BrokenEdgeAligner → optimistic-lock schema_hash re-check → emit YAML. `time_budget.py` (`TimeBudgetController`) enforces wall-clock budget. `_build_subgraph_config()` performs deterministic CHECK-constraint inference before any LLM call (see gotchas below).
- **Layer 6 — `analyzer/`** — LLM table-level analysis with streaming/tool-calling submodules (`_caller`, `_streaming`, `_tool_calling` [protocol-based: `gemma4`/`openai`/`none`], `_context`, `_json_parser`). Used by the non-auto-heal `ai-suggest` path.

**sqlseed-ai file inventory (subpackages, by layer)**:

| Subpackage | Files | Key files (lines) |
|:-----------|------:|:------------------|
| `contracts/` (L1) | 4 | `builtin_violations.py` [334L], `registry.py` [277L] LearnedContractsRegistry, `matrix.py` [183L] ContractResolver |
| `validator/` (L2) | 9 | `single_column.py` [331L], `schema_snapshot.py` [218L], `cross_column.py` [188L], `shadow_fk_scan.py` [154L], `main.py` [95L] FastValidator |
| `repair/` (L3) | 5 | `strategies.py` [776L] REPAIR_STRATEGIES, `executor.py` [101L], `pipeline.py` [57L], `models.py` [39L] |
| `healer/` (L4) | 14 | `orchestrator.py` [559L] HealOrchestrator, `level2_column_healer.py` [313L], `level1_subgraph_healer.py` [206L], `degrader.py` [245L], `level3_compact_healer.py` [190L], `subgraph.py` [160L] TarjanSCC, `models.py` [149L] 10 dataclasses |
| `auto_heal/` (L5) | 3 | `orchestrator.py` [6619L] AutoHealOrchestrator, `time_budget.py` [44L] TimeBudgetController |
| `analyzer/` (L6) | 7 | `_caller.py` [434L], `_streaming.py` [308L], `_context.py` [262L], `__init__.py` [68L] SchemaAnalyzer, `_json_parser.py` [141L], `_tool_calling.py` [141L] |
| root | 17 | `refiner.py` [819L] AiConfigRefiner, `config.py` [642L] AIConfig, `mcp.py` [410L] 3 Gemma tools, `__init__.py` [326L] AISqlseedPlugin, `_prompts.py` [301L], `examples.py` [278L], `_hardware.py` [345L] |
| `cli/` | 3 | `ai_commands.py` [928L] ai_suggest/ai_analyze/auto_heal + register() |

**Gotchas when editing this subsystem**:
- The `auto_heal.orchestrator` runs multiple convergence rounds; many `git log` entries are "Round N" fixes for specific cross-column CHECK patterns (Pattern 1/1b/4a/7a/7b/19/21/22/22c/24b/etc.). These are real constraint-handling rules, not throwaway — grep for the pattern number before removing.
- `degrader.py` is the "semantic downgrade safety net" — stripping generator/params when `derive_from` is present is intentional (see commit `78d15f9`).
- Self-referencing and composite FK resolution has many edge-case fixes (two-pass fill, `null_ratio=1.0` for empty-parent FK). See recent commits before changing `relation.py` / `_generation.py`.
- `refiner.py` delegates Rule #14 param stripping to v4 `REPAIR_STRATEGIES["normalize_params"]` — don't re-implement there.
- The legacy `Stage3Validator` (36 numbered rules), `SchemaSemanticAnalyzer`, and `StagedSchemaAnalyzer` were deleted in Phase 4 zero-rot cleanup — no dual-track system. Migration: Rule #14 → `normalize_params`; Rule #26 → `coerce_float_to_int`; Rule #35 → derive_from cleanup; Rule #36 → date-column generator coercion. Full matrix in `docs/superpowers/plans/v4_coverage_matrix.md`.

## DOCS TO READ BEFORE SENSITIVE EDITS

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — authoritative architecture reference (4-package layout, plugin contracts, core-stability principle). Read before touching package boundaries or public API.
- **[CLAUDE.md](./CLAUDE.md)** — canonical "Never/Always" rules (the import-linter contracts encode these). Read before core changes.

## DOC SYNC RULES

When modifying these source files, update the corresponding docs in the **same commit**:

| Source File | Docs to Update | What to Check |
|:------------|:---------------|:--------------|
| `src/sqlseed/generators/_dispatch.py` | README.md, README.zh-CN.md | Generator type table (count + names) |
| `src/sqlseed/core/mapper.py` | README.md, CLAUDE.md | Exact match rule count, pattern match count |
| `src/sqlseed/core/expression.py` | README.md, README.zh-CN.md | SAFE_FUNCTIONS table (count + names) |
| `src/sqlseed/plugins/hookspecs.py` | README.md, CLAUDE.md, AGENTS.md, docs/architecture.md | Hook table (count + names) |
| `src/sqlseed/config/models.py` | docs/architecture.md, docs/architecture.zh-CN.md | Class diagrams (field names + types) |
| `plugins/sqlseed-cli/src/sqlseed_cli/main.py` | README.md, README.zh-CN.md | CLI command reference |
| `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` | README.md, README.zh-CN.md | AI CLI command reference |
| `src/sqlseed/__init__.py` | README.md, README.zh-CN.md | Public API table |

Doc files use `<!-- BEGIN:AUTO-GENERATED:marker-name -->value<!-- END:AUTO-GENERATED:marker-name -->` markers for automated count verification. **Don't manually edit values inside markers** — run `scripts/sync_docs.py`, then `pytest tests/test_doc_sync.py` to verify.

## COMMANDS

A `Makefile` wraps the common flows (`make help` lists all targets). Both forms work.

```bash
# Install core + plugins (dev mode)
pip install -e ".[dev,all]"
pip install -e "./plugins/sqlseed-cli"
pip install -e "./plugins/sqlseed-ai"
pip install -e "./plugins/mcp-server-sqlseed"
pip install -e "./plugins/sqlseed-ui"

# Test
pytest                              # All tests (core + plugins)
make test-core                      # Core only (test_core/test_config/test_database/test_generators/test_plugins)
pytest plugins/sqlseed-ai/tests/    # AI plugin only
pytest tests/test_orchestrator.py -v            # Single file
pytest -k "test_fill" -v                         # Pattern match
pytest --cov=sqlseed.core.orchestrator --cov-report=term-missing   # Focused coverage
make test-integration              # Requires Docker (PostgreSQL)

# Lint / type-check / layer contracts (run all before merge)
ruff check src/ tests/ plugins/     # or: make lint  (also lints examples/)
ruff format src/ tests/ plugins/    # or: make format
mypy src/sqlseed/ plugins/          # or: make type-check
lint-imports                        # architectural layer contracts (CI gate)

# Mutation testing
make mutmut                         # Windows: needs mutmut<3 + PYTHONUTF8=1
make mutmut-report                  # show survivors (then: python -m mutmut show <id>)
make mutmut-clean                   # remove .mutmut-cache and survivor reports

# Docs
make docs-serve                     # mkdocs serve
make docs-build                     # mkdocs build --strict

# CLI (requires sqlseed-cli installed)
sqlseed fill app.db -t users -n 10000
sqlseed preview app.db -t users -n 5
sqlseed inspect app.db --show-mapping
```

## TEST FIXTURES (root `conftest.py`)

Core fixtures (auto-discovered from the root `conftest.py`; plugin conftests only reuse helper functions from `tests/conftest.py` via importlib):

- `tmp_db_simple` — simple single-table DB (id + name)
- `tmp_db_full` — full multi-table DB (users + orders with FK)
- `tmp_db` — backward-compatible alias for `tmp_db_full`
- `tmp_db_with_data` — `tmp_db` pre-populated with 10 user rows
- `unique_test_db` — projects table with unique indexes
- `raw_adapter` / `raw_adapter_with_data` — `RawSQLiteAdapter` instances
- `gc_between_tests` — opt-in garbage collection for memory-sensitive tests
- `pg_url` (session-scoped) — testcontainers PostgreSQL, **requires Docker**
- `available_llm_backend` (session-scoped) — auto-detects Ollama / LM Studio / Google AI Studio
- Helper functions: `make_column_info()` factory, `create_project_info_db()`, `create_simple_db()`, `apply_enrichment()`

**Rules**:
- Use real SQLite via `tmp_path`, never mock the database layer (mocks create self-proving tests — see Pitfall #13).
- CLI tests: `click.testing.CliRunner`, never subprocess.
- AI plugin tests: `pytest.importorskip("sqlseed_ai")`.
- Integration tests: `tests/integration/` with `@pytest.mark.integration` marker.
- Benchmarks: `tests/benchmarks/` with `pytest-benchmark`.

## RELEASE CHECKLIST

When preparing a new version release:

1. **`uv.lock` files** — There are 3 lock files, all must stay in sync with their `pyproject.toml`:
   - `./uv.lock` (root)
   - `./plugins/sqlseed-ai/uv.lock`
   - `./plugins/mcp-server-sqlseed/uv.lock`

   Run `uv lock` in each directory after any `pyproject.toml` dependency change. (`plugins/sqlseed-cli/` has no separate lock — it pins `sqlseed` core.)

2. **Changelog** — Update both `CHANGELOG.md` and `CHANGELOG.zh-CN.md` with the new version number.

3. **Tag & Release** — After pushing all commits:
   ```bash
   git tag v<version>
   git push origin v<version>
   gh release create v<version> --title "v<version>" --generate-notes
   ```

4. **CI publish** — `publish.yml` triggers on release or `workflow_dispatch`. If PyPI publish fails on sigstore attestation (`ChunkedEncodingError`), this is a known upstream issue (pypa/gh-action-pypi-publish#364) — re-run via the GitHub Actions UI.

## NOTES

- **Optional deps**: mimesis is optional. faker is a required core dependency. Base provider is type-routing only (no real data generation).
- **Plugin isolation**: sqlseed-cli, sqlseed-ai, mcp-server-sqlseed each have separate pyproject.toml, install separately. `mcp-server-sqlseed` installs as package `mcp-server-sqlseed` but its import module is **`mcp_server_sqlseed`** (hyphens → underscores); `server.py` exposes the FastMCP server, `__main__` is the entrypoint.
- **Core has no CLI**: `src/sqlseed/` has no `cli/` directory. Install `sqlseed-cli` to get the `sqlseed` command. Core has no `[project.scripts]`.
- **mypy strict**: Strict on `src/` and `plugins/` source code; test directories (`tests/`, `plugins/*/tests/`) excluded.
- **ruff config**: Line length 120, isort known-first-party=["sqlseed"], known-third-party=["sqlseed_ai", "sqlseed_cli", "mcp_server_sqlseed"].
- **Test layout**: Core tests in `tests/`; plugin tests co-located with plugins (`plugins/*/tests/`). Fixtures live in the root `conftest.py` (auto-discovered); plugin conftests only reuse helper functions from `tests/conftest.py` via importlib.
- **`scripts/` is scratch**: regression logs, generated `.db`/`.sql`/`.yaml` files, and ad-hoc harnesses. Useful as references for the self-healing scenarios but not shipped artifacts — don't rely on their contents being stable.
- **Sibling agent files**: `CLAUDE.md` is the canonical rules source (Never/Always + Critical Pitfalls + Key Modules detail); `GEMINI.md` is a pointer to `CLAUDE.md` (single source of truth — don't reconcile them as divergent copies). `AGENTS.md` (this file) is the project knowledge base index. All three are kept in sync; when in doubt, `CLAUDE.md` wins on rules, `ARCHITECTURE.md` wins on architecture decisions.
