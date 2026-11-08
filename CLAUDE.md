# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is sqlseed

Python 3.10+ declarative multi-database test data generation toolkit. Single API call infers schema, picks generators via 9-level column mapping, streams data in batches, and maintains FK integrity across tables. Supports SQLite (default) and PostgreSQL via SQLAlchemy. MySQL was removed (deferred until PostgreSQL is fully validated). Optional plugins add CLI (`sqlseed-cli`), AI-powered schema analysis (`sqlseed-ai`, including Gemma 4 model/protocol support), MCP server (`mcp-server-sqlseed`), and browser workbench (`sqlseed-web`).

**Stack**: hatchling + hatch-vcs build, ruff lint, mypy strict, pytest. License: AGPL-3.0-or-later.

**Architecture**: 5 independent packages — `sqlseed` (core, offline Python API), `sqlseed-cli` (CLI plugin), `sqlseed-ai` (AI plugin), `mcp-server-sqlseed` (MCP plugin), and `sqlseed-web` (Web plugin). See [ARCHITECTURE.md](./ARCHITECTURE.md) for the authoritative architecture reference.

## Quick Start Commands

```bash
# Resolve Core and all local plugins from this checkout together
python -m pip install -e ".[dev,all]" -e "./plugins/sqlseed-cli" -e "./plugins/sqlseed-ai[dev]" -e "./plugins/mcp-server-sqlseed" -e "./plugins/sqlseed-web[dev]"

# Run all tests (core + all plugin tests)
pytest

# Run a single test file
pytest tests/test_orchestrator.py -v

# Run tests matching a pattern
pytest -k "test_fill" -v

# Run with coverage for a specific module
pytest --cov=sqlseed.core.orchestrator --cov-report=term-missing

# Lint and auto-fix
ruff check --fix src/ tests/ plugins/

# Format
ruff format src/ tests/ plugins/

# Type check (uses pyproject.toml config — strict on src/ and plugins/, excludes tests/)
mypy

# Architecture layer contracts (CI gate; [tool.importlinter] in pyproject.toml)
make lint-imports

# Subsets
make test-core           # tests/test_core, test_config, test_database, test_generators, test_plugins
make test-integration    # tests/integration/ (requires Docker)

# Doc sync: refresh AUTO-GENERATED markers (--check exits 1 if stale)
python scripts/sync_docs.py
pytest tests/test_doc_sync.py

# Release notes validation (before tagging)
python scripts/sync_release_notes.py --check

# CLI usage
sqlseed fill app.db -t users -n 10000
sqlseed preview app.db -t users -n 5
sqlseed inspect app.db --table users --show-mapping  # View column mapping strategies
sqlseed init generate.yaml --db app.db               # Generate config template
sqlseed fill app.db -t users -n 10000 --snapshot      # Save snapshot for replay
sqlseed replay <cache_dir>/snapshots/YYYY-MM-DD_users.yaml  # Replay from snapshot
SQLSEED_LOG_LEVEL=DEBUG sqlseed fill app.db -t users -n 10  # Debug logging
SQLSEED_CACHE_DIR=./my_cache sqlseed fill app.db -t users -n 100 --snapshot  # Custom cache dir

# Multi-DB connections via --url
sqlseed fill --url "postgresql+psycopg://user:pass@host/db" -t users -n 1000
sqlseed inspect --url "postgresql+psycopg://user:pass@host/db"
```

## Architecture

Layered design with strict dependency direction (`→` means "depends on"):

```
plugins/sqlseed-cli/  ──┐
plugins/sqlseed-ai/   ──┼──→  sqlseed (core)  ──→  generators/
plugins/mcp-server-sqlseed/ ─┤                    database/
plugins/sqlseed-web/ ───────┘                     plugins/
                                                  config/

_utils/ → (no internal deps, used by all layers)
```

Core (`sqlseed`) has **no CLI, AI, MCP or Web application code** — these are all plugins. Core never depends on `click`, `rich`, `openai`, or `mcp`.

**Never**: `generators` → `core`, `database` → `core`, `_utils` → any upper layer, `core` → any plugin.

### Key Modules

- **`core/orchestrator/`** — Package (refactored from single file). `DataOrchestrator` is the central coordinator, composed via multiple inheritance from 4 mixins + 1 shared data module (plus 2 helper modules; `tests/test_architecture.py` guards the 5 core files):
  - `_common.py` — Shared dataclasses (not a mixin): `CoreCtx` (db, schema, mapper, relation, shared_pool), `ExtCtx` (registry, plugins, plugin_mediator, enrichment, unique_adjuster, schema_fallback, metrics). Helper: `_is_db_url()`.
  - `_connection.py` — `ConnectionMixin`: lifecycle (`__init__`, `_ensure_connected`, `close`), adapter creation, property accessors for all `_core`/`_ext` fields, context manager protocol, `from_config()` classmethod.
  - `_specs.py` — `SpecResolverMixin`: `_resolve_specs()` (schema inference → column mapping → enrichment → unique adjustment → FK resolution), `_build_stream()` (also extracts cross-column comparison CHECK constraints `col1 OP col2` into `inequality_constraints` for row-level enforcement), `_prepare_specs()` (AI suggestion/template pool application), `_resolve_user_configs()`.
  - `_generation.py` — `GenerationMixin`: `_generate_and_insert_batches()`, `fill_table()` (main entry point), `preview_table()`. `fill = fill_table` alias.
  - `_query.py` — `QueryMixin`: `get_schema_context()`, `get_column_mapping()`, `get_column_names()`, `get_skippable_columns()`, `get_topological_table_order()`, `get_table_names()`, `get_column_info()`, `get_foreign_keys()`, `get_row_count()`, `execute()`, `query()`, `fetch_one()`, `report()`, `map_column()`.
  - `_self_ref.py` — `SelfReferenceUpdater` (helper, not a mixin): fills deferred self-referencing FKs after insertion using complete row identities and UNIQUE probes; rows with no fitting parent keep a valid NULL.
  - `_session.py` — `FillSession` (helper dataclass): per-fill accounting into `GenerationResult`. Counters advance only after the adapter acknowledges a commit — it does not claim transaction-wide atomicity.
- **`core/mapper.py`** — `ColumnMapper` with 9-level strategy chain (L1: autoincrement PK → L2: user config → L3: exact match (custom + built-in) → L4: default value / nullability → L5: pattern match (custom + built-in) → L6: CamelCase→snake_case exact retry → L7: snake_case pattern retry → L8: nullable fallback → L9: type fallback). <!-- BEGIN:AUTO-GENERATED:exact-match-rule-count -->75<!-- END:AUTO-GENERATED:exact-match-rule-count --> exact rules, <!-- BEGIN:AUTO-GENERATED:pattern-match-rule-count -->29<!-- END:AUTO-GENERATED:pattern-match-rule-count --> regex patterns.
- **`core/schema.py`** — `SchemaInferrer` reads database schema via adapter. Methods: `get_column_info()`, `detect_unique_columns()`, `get_index_info()`, `get_sample_data()`, `profile_column_distribution()`.
- **`core/relation.py`** — `RelationResolver` + `SharedPool` for cross-table FK integrity. Implicit associations via name matching, explicit via `ColumnAssociation` config. `topological_sort()` for multi-table fill ordering — uses Kahn's algorithm with graceful cycle-breaking (logs a warning and picks the first table in input order to break circular FK dependencies, e.g., `branches↔employees`; does NOT raise `ValueError`).
- **`core/column_dag.py`** — Topological sort for `derive_from` column dependencies.
- **`core/expression.py`** — `ExpressionEngine` using `simpleeval`. Timeout via thread (5s default). `ExpressionTimeoutError` on timeout. Whitelisted functions live in `SAFE_FUNCTIONS` (reference list in docs/guide.md).
- **`core/constraints.py`** — `ConstraintSolver` for UNIQUE enforcement with backtracking. Supports probabilistic mode (SHA256 hash-based) for >100K rows.
- **`core/stream.py`** — `DataStream` for batch data generation with constraint backtracking. Generates data column-by-column following the DAG node order. `composite_unique_constraints` enforces multi-column UNIQUE at row level. `inequality_constraints` (list of `(col1, col2, op)` tuples where op ∈ `!=`, `>`, `<`, `>=`, `<=`) enforces cross-column comparison CHECK constraints at row-generation time — when violated, the row is rolled back and retried. This prevents batch-level `IntegrityError` when both columns are independently sampled (e.g., `start_time`/`end_time` with LIKE constraints that block `derive_from`, or `origin_wh_id`/`dest_wh_id` with `CHECK(origin != dest)`). 2-tuple `(col1, col2)` form is backwards-compatible (defaults to `!=`).
- **`core/enrichment.py`** — Local enum detection + enrichment (no AI logic; stays entirely in core). Detects enum columns from existing data distribution and applies local column-mapping enrichment. AI-suggested mappings are applied via the `sqlseed_apply_ai_suggestions` pluggy hook (implemented in `sqlseed-ai`).
- **`core/unique_adjuster.py`** — Post-generation UNIQUE constraint adjustment.
- **`core/plugin_mediator.py`** — Bridges plugins and core (not direct calls). Generic methods only: `apply_batch_transforms()`, `apply_template_pool()`. AI-specific `apply_ai_suggestions()` was moved to `plugins/sqlseed-ai/` (Phase C) and is invoked via the `sqlseed_apply_ai_suggestions` pluggy hook.
- **`core/transform.py`** — Row/batch transform pipeline. `load_transform(path)` loads user transform scripts.
- **`core/result.py`** — `GenerationResult` dataclass for generation results (table_name, count, elapsed, rows_per_second, batch_count, errors).
- **`generators/`** — `DataProvider` protocol: `name`, `set_locale`, `set_seed`, `generate(type_name, **params)`. Generator types are dispatched via `GeneratorDispatchMixin.GENERATOR_MAP` (complete table + AUTO-GENERATED count in docs/guide.md). Three providers: `BaseProvider` (built-in synthesized values), `FakerProvider` (required, standard), `MimesisProvider` (optional, high-performance).
- **`database/`** — `DatabaseAdapter` protocol with `SQLAlchemyAdapter` (required core dependency, supports SQLite/PostgreSQL via SQLAlchemy) and `RawSQLiteAdapter` (test-only fallback). Dialect abstraction in `_dialect.py`, type normalization in `_type_normalizer.py`, bulk write optimization in `_bulk_optimizer.py`. Additional: `_base_adapter.py` (shared base), `_helpers.py` (batch insert helpers), `optimizer.py` (PRAGMA optimization), `_sqlite_schema.py` (SQLite-specific autoincrement detection via `sqlite_master`). MySQL support was removed (Phase A).
- **`plugins/`** — 12 pluggy hooks. `PluginManager` + `PluginMediator` bridge plugins and core. This is the plugin **infrastructure** (hookspecs + manager); actual plugin implementations live in `plugins/sqlseed-cli/`, `plugins/sqlseed-ai/`, `plugins/mcp-server-sqlseed/`.
- **`config/`** — Pydantic models (`GeneratorConfig`, `TableConfig`, `ColumnConfig`, `ColumnConstraintsConfig`, `ColumnAssociation`, `ProviderType`), YAML/JSON loader, `SnapshotManager` (save/load/list_snapshots; CLI `replay` command uses `SnapshotManager.load()` + `DataOrchestrator.from_config()`).
- **`_utils/paths.py`** — Platform-aware cache directory resolution (`get_cache_dir()`). Supports macOS/Linux/Windows, overridable via `SQLSEED_CACHE_DIR` env var.
- **`_utils/sql_safe.py`** — SQL identifier quoting (`quote_identifier()`), table name validation (`validate_table_name()`), insert SQL generation (`build_insert_sql()`).
- **`_utils/progress.py`** — Progress bar abstraction (`ProgressBackend` protocol) with Rich and tqdm backends, factory `create_progress()`.
- **`_utils/metrics.py`** — `MetricsCollector` for performance metrics.
- **`_utils/logger.py`** — Structured logging via `structlog`. `get_logger()`, `configure_logging()`.
- **`plugins/sqlseed-ai/{contracts,validator,repair,healer,auto_heal}/`** — v4 contract-driven self-healing architecture (6 layers, default path). Replaced the legacy `Stage3Validator` (36 numbered rules) and `SchemaSemanticAnalyzer`/`StagedSchemaAnalyzer` (deleted in Phase 4 zero-rot cleanup). See [v4 Contract-Driven Self-Healing (sqlseed-ai)](#v4-contract-driven-self-healing-sqlseed-ai) below.

> **Note**: The `cli/` directory no longer exists in `src/sqlseed/` — CLI code moved to `plugins/sqlseed-cli/` (Phase B). Core `pyproject.toml` has no `[project.scripts]` entry.

### Public API (`src/sqlseed/__init__.py`)

| Entry | Purpose |
|----------|---------|
| `fill(db_path, *, url, table, count, ...)` | Single table zero-config fill |
| `FillOptions(...)` | Frozen, keyword-only reusable fill settings; explicit fill keywords take precedence |
| `connect(db_path, *, url, ...)` | Returns `DataOrchestrator` context manager |
| `preview(db_path, *, url, table, count, ...)` | Preview data without writing |
| `fill_from_config(config_path)` | Batch fill from YAML/JSON config |
| `load_config(path)` | Load config as `GeneratorConfig` |

`fill`, `connect`, and `preview` accept `db_path` (SQLite file) and `url` (database URL) as mutually exclusive connection modes. `fill_from_config` and `load_config` take configuration paths instead.

### Config Model Hierarchy

`GeneratorConfig` → `list[TableConfig]` → `list[ColumnConfig]` + `list[ColumnAssociation]`

`GeneratorConfig` has mutually exclusive `db_path` / `url` fields; `connection_target` property returns whichever is set.

`ColumnConfig` contains optional `constraints: ColumnConstraintsConfig` (unique, min_value, max_value, regex, max_retries with ge=0).

ColumnConfig supports two mutually exclusive modes (enforced by Pydantic `model_validator`):
- **Source mode**: `generator` + `params` + `null_ratio` + `provider`
- **Derived mode**: `derive_from` + `expression`

ColumnConfig also supports `faker_method`, `mimesis_method`, and `native_params` for native method overrides, including native-only sources without `generator`. Matching native methods remain active during UNIQUE retries; unsupported methods/parameters fail explicitly. Generic UNIQUE widening must preserve native source selection.

### Plugin Hooks (12 total)

| Hook | firstresult | When |
|------|:-----------:|------|
| `sqlseed_register_providers(registry)` | ✗ | `_ensure_connected()` |
| `sqlseed_register_column_mappers(mapper)` | ✗ | `_ensure_connected()` |
| `sqlseed_ai_analyze_table(...)` | ✓ | `sqlseed_apply_ai_suggestions()` (low-level LLM call) |
| `sqlseed_apply_ai_suggestions(...)` | ✓ | Orchestrator `_resolve_specs()` (high-level AI mediation; implemented in `sqlseed_ai.ai_mediator`) |
| `sqlseed_before_generate(table_name, count, config)` | ✗ | Before main generation loop |
| `sqlseed_after_generate(table_name, count, elapsed)` | ✗ | After generation completes |
| `sqlseed_transform_row(table_name, row)` | ✗ | Declared hookspec; not dispatched by normal Core generation |
| `sqlseed_transform_batch(table_name, batch)` | ✗ | `apply_batch_transforms()`; same batch input, last non-`None` result wins |
| `sqlseed_before_insert(table_name, batch_number, batch_size)` | ✗ | Before each batch write |
| `sqlseed_after_insert(table_name, batch_number, rows_inserted)` | ✗ | After each batch write |
| `sqlseed_shared_pool_loaded(table_name, shared_pool)` | ✗ | After `register_shared_pool()` |
| `sqlseed_pre_generate_templates(...)` | ✓ | `apply_template_pool()` |

### v4 Contract-Driven Self-Healing (sqlseed-ai)

The `sqlseed-ai` plugin uses the **v4 contract-driven self-healing architecture** as the default and only schema-analysis path. The legacy `Stage3Validator` (36 numbered rules), `SchemaSemanticAnalyzer`, and `StagedSchemaAnalyzer` were deleted in Phase 4 zero-rot cleanup — no dual-track system, no deprecated flags, no transitional bridges.

v4 is a 6-layer pipeline built on the open-closed principle: core code (Registry + Validator + Executor) is closed; rules are open for extension via the `REPAIR_STRATEGIES` dict.

- **Layer 1 — `contracts/`**: Sparse contract matrix + resolver. `ContractViolation` defines a single bad generator/type/constraints combination; `ContractResolver` merges builtin + learned violations with specificity-priority matching. The matrix is a *closed set* — only known-bad combinations are listed; unlisted combinations default to COMPATIBLE. `builtin_violations.py` ships the seed violations; `registry.py` exposes the lookup API.
- **Layer 2 — `validator/`**: `FastValidator` (in `main.py`) orchestrates five components: `SingleColumnValidator` (2a: per-column contract + cardinality), `CrossColumnValidator` (2b: FK integrity + derive_from DAG cycle detection), `DialectErrorParser` (Defense 3: normalize DBAPI exceptions to `ViolationReport`), `ShadowFKScanner` (Section 14.3: localize SQLite FK violation column), and `CompositeFKCoordinator` (multi-column FK). `schema_snapshot.py` records `schema_hash` at startup for optimistic-lock re-check at write time (Defense 8). `models.py` defines `ConstraintType`, `ViolationReport`, `ValidationResult`.
- **Layer 3 — `repair/`**: Stateless repair engine. Each strategy is a pure function `RepairFn = Callable[[dict, ViolationReport, dict], dict]` registered in `REPAIR_STRATEGIES`. `strategies.py` ships the canonical strategies — notably `normalize_params` (v4 replacement for legacy Rule #14: strips params not in `_GENERATOR_PARAM_WHITELIST` for ALL generators, 36 entries aligned with `base_provider.py` signatures), `coerce_float_to_int` (legacy Rule #26: `random_float` → `random_int` for INTEGER columns), plus derive_from cleanup, date-column generator fixes, and CHECK-chain mirroring. `executor.py` applies strategies by `fix_hint` dispatch; `pipeline.py` chains them.
- **Layer 4 — `healer/`**: 4-level LLM heal architecture with failure-type-aware routing. `orchestrator.py` (`HealOrchestrator`) coordinates 4-level degradation: Level 1 (subgraph) → Level 2 (column) → Level 3 (compact) → Level 4 (deterministic degrade). `context_detector.py` (`ContextWindowDetector`) dynamically detects model context window size (priority: `AIConfig.max_context_tokens` → model map → default 4096) and pre-judges whether to skip Level 1 (skip if token estimate > 60% of context window). `failure_classifier.py` (`FailureClassifier`) classifies LLM failures into 6 types (`CONTEXT_OVERFLOW`, `EMPTY_RESPONSE`, `JSON_FORMAT`, `SEMANTIC`, `NETWORK`, `UNKNOWN`) for routing decisions. `level1_subgraph_healer.py` (`Level1SubgraphHealer`) sends the entire subgraph to the LLM (default path). `level2_column_healer.py` (`Level2ColumnHealer`) sends only the target column + complete dependency set (CHECK constraints, derive_from sources, cross-column refs, FK info) — information boundary optimization for context overflow. `level3_compact_healer.py` (`Level3CompactHealer`) uses compact/ultra-compact prompts + JSON repair for format errors. `degrader.py` (`ProgressiveDegrader`) is the deterministic fallback (unchanged). `oscillation.py` detects repeated failures (same error type reset on type change). `subgraph.py` (`SubgraphSplitter`) does Tarjan SCC + megacluster breaking (Defenses 2 + 6). `post_repair.py` (`BrokenEdgeAligner`) repairs broken FK edges. `diff_learner.py` persists learned violations back to Layer 1. `_client.py` provides the shared `LLMClient` protocol + `OpenAICompatAdapter`. Routing: `CONTEXT_OVERFLOW`/`EMPTY_RESPONSE` → Level 2; `JSON_FORMAT` → Level 3 (skip Level 2); `SEMANTIC` → Level 4 (skip Level 2/3); `NETWORK` → raise exception. `Layer4Coordinator` and `LLMHealer` were deleted (replaced by the 4-level architecture).
- **Layer 5 — `auto_heal/`**: `AutoHealOrchestrator` (`orchestrator.py`) is the top-level entry point for `ai-analyze` (default v4 path), `ai-suggest --auto-heal`, and the standalone `auto-heal` command. Pipeline: SchemaSnapshot → SubgraphSplitter → per-subgraph (Layer 2 validate → Layer 3 repair → Layer 4 heal) → BrokenEdgeAligner → optimistic-lock schema_hash re-check → emit YAML. `time_budget.py` (`TimeBudgetController`) enforces a wall-clock budget. Before any LLM call, `_build_subgraph_config()` infers column configs deterministically from CHECK constraints: single-column patterns (LENGTH/IN/BETWEEN/ranges/LIKE→regex, `col IS NULL OR …` prefix stripping, multi-CHECK bound merging) live in `_check_inference.py`; the large cross-column pattern catalog (`_infer_cross_column_config()` — comparisons, arithmetic chains, conditional NULL/enum/range, reverse sums, self-ref FK conditions; each pattern is documented inline) lives in `_cross_column_checks.py`. After the LLM responds, "Step 5.5" in `run()` applies safety nets (hallucinated/`?` generator repair, param re-inference from CHECKs, cross-column `derive_from` restoration, `_strip_invalid_params`). Non-obvious invariants to preserve when adding patterns: float comparisons use addition/subtraction, never multiplication (negative source values would reverse the inequality); exact-sum addends use `random_int` so `=` CHECKs hold exactly in IEEE 754; FK columns get `None`, not `0`, in conditional-NULL branches; columns (or sources) with a LIKE constraint never get arithmetic `derive_from` and are forced to the `pattern` generator.
- **Layer 6 — `analyzer/`**: LLM table-level analysis with streaming/tool-calling submodules (`_caller.py`, `_streaming.py`, `_tool_calling.py` [protocol-based: `gemma4`/`openai`/`none`], `_context.py`, `_json_parser.py`). Used by the non-auto-heal `ai-suggest` path.

The legacy `Stage3Validator` rules are migrated to v4 strategies as follows (non-exhaustive): Rule #14 → `normalize_params`; Rule #22 → deferred `_has_date_year_range` check (runs after derive_from processing); Rule #26 → `coerce_float_to_int`; Rule #35 → derive_from cleanup for non-timedelta date expressions; Rule #36 → date-column generator coercion. The full migration coverage matrix is in [`docs/superpowers/plans/v4_coverage_matrix.md`](./docs/superpowers/plans/v4_coverage_matrix.md).

## Coding Conventions

- Every `.py` file starts with `from __future__ import annotations`
- All public functions use keyword-only arguments (except `generate_choice(choices)`)
- Never use `assert` for runtime validation — use `RuntimeError`/`ValueError` instead (asserts can be optimized away with `-O`)
- SQL identifiers: always use `quote_identifier()` from `_utils/sql_safe.py`
- Logging: `structlog` via `sqlseed._utils.logger.get_logger(__name__)`
- New config models: Pydantic `BaseModel`
- New providers/adapters: must satisfy existing `Protocol` definitions
- Optional deps (mimesis): always lazy import with try/except
- Register new providers via `pyproject.toml` `[project.entry-points."sqlseed"]`
- **Ruff config**: Line length 120, isort `known-first-party=["sqlseed"]`, `known-third-party=["sqlseed_ai", "sqlseed_cli"]`
- **Mypy scope**: Strict on `src/` and `plugins/` source code; test directories (`tests/`, `plugins/*/tests/`) are excluded from mypy (relaxed)

### Import Style

```python
# Type-only imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo

# Optional deps: lazy import inside methods
def method(self):
    import sqlalchemy  # not at module top
```

## Doc Sync Rules

When modifying these source files, update the corresponding docs in the same commit:

| Source File | Docs to Update | What to Check |
|:------------|:---------------|:-------------|
| `src/sqlseed/generators/_dispatch.py` | docs/guide.md | Complete Generators table and AUTO-GENERATED count; README keeps entry points and examples |
| `src/sqlseed/core/mapper.py` | docs/guide.md, docs/architecture.md, docs/architecture.zh-CN.md, CLAUDE.md | Exact match rules and pattern match counts |
| `src/sqlseed/core/expression.py` | docs/guide.md | Expressions and SAFE_FUNCTIONS reference |
| `src/sqlseed/plugins/hookspecs.py` | docs/guide.md, docs/architecture.md, docs/architecture.zh-CN.md, CLAUDE.md | Hook reference and counts |
| `src/sqlseed/config/models.py` | docs/architecture.md, docs/architecture.zh-CN.md | Class diagrams (field names + types) |
| `plugins/sqlseed-cli/src/sqlseed_cli/main.py` | docs/guide.md, CLI package README | Full CLI reference; root READMEs retain introductory examples |
| `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` | docs/guide.md, AI package READMEs | Full AI CLI reference; root READMEs retain command purposes |
| `src/sqlseed/__init__.py` | docs/api.md, README.md, README.zh-CN.md | Full API reference, entry-point table, and examples |

Run `pytest tests/test_doc_sync.py` to verify doc sync after changes. Automated count verification uses paired HTML comments named `BEGIN:AUTO-GENERATED:<name>` and `END:AUTO-GENERATED:<name>`, with the generated value between them.

## Testing

- **Test layout** (Phase F): Core tests in `tests/`; plugin tests co-located with their plugins:
  - `tests/` — core tests (orchestrator, mapper, schema, generators, database, config, etc.)
  - `plugins/sqlseed-cli/tests/` — CLI tests (moved from `tests/` in Phase F)
  - `plugins/sqlseed-ai/tests/` — AI plugin tests (moved from `tests/` in Phase F)
  - `plugins/mcp-server-sqlseed/tests/` — MCP server tests
  - `plugins/sqlseed-web/tests/` — Web workbench tests (all five dirs are in `pyproject.toml` `testpaths`, so bare `pytest` runs them)
  - Plugin conftest files re-export root `tests/conftest.py` fixtures via `from tests.conftest import ...`
- Fixtures in `tests/conftest.py`:
  - `tmp_db_simple` — simple single-table database (id + name)
  - `tmp_db_full` — full multi-table database (users + orders with FK)
  - `tmp_db` — backward-compatible alias for `tmp_db_full`
  - `tmp_db_with_data` — `tmp_db` pre-populated with 10 user rows
  - `unique_test_db` — projects table with unique indexes
  - `raw_adapter` / `raw_adapter_with_data` — `RawSQLiteAdapter` instances
  - `gc_between_tests` — opt-in garbage collection for memory-sensitive tests
  - `pg_url` (session-scoped) — testcontainers PostgreSQL, requires Docker
  - `available_llm_backend` (session-scoped) — auto-detects Ollama/LM Studio/Google AI Studio
  - Helper functions: `make_column_info()` factory, `create_project_info_db()`, `create_simple_db()`, `apply_enrichment()`
- Use real SQLite via `tmp_path` fixture, never mock the database layer
- CLI tests: use `click.testing.CliRunner`, never subprocess
- AI plugin tests: `pytest.importorskip("sqlseed_ai")`
- Integration tests: `tests/integration/` directory with `test_pg_integration.py` (requires Docker + testcontainers) and `test_url_e2e.py`
- Benchmarks: `tests/benchmarks/` with `pytest-benchmark`
- Integration test marker: `@pytest.mark.integration`
- Architecture guard tests: `tests/test_architecture.py` (invariant tests verifying module boundaries, production isolation, count contracts, public API surface) — complement `lint-imports` and the `[tool.importlinter]` contracts in `pyproject.toml`.
- Mutation testing (mutmut): `make mutmut` runs mutation tests on `src/sqlseed/core/unique_adjuster.py` by default. Override with `--paths-to-mutate` and `--runner` CLI flags to test other modules. The current survival baseline is recorded in the comment above `[tool.mutmut]` in `pyproject.toml`; use `make mutmut-report` to inspect surviving mutants. **Surviving mutants indicate self-proving tests** — tests that pass because mocks returned what the author expected, not because the production code actually computes the right thing. When adding new core code or strengthening tests, run `make mutmut` and check that the survival rate does not increase.

## Critical Pitfalls

Explicit generator overrides inherit name-rule defaults only when compatible: the same generator retains defaults, while cross-`string`/`text` inheritance is limited to `min_length`/`max_length`. Never inject length parameters into `sentence` or `charset` into `text`. Preserve explicit user parameters so unsupported values still fail validation.

Preserve explicit contradictory length limits for validation. SQLite PK generation skips only metadata-confirmed rowid aliases; `WITHOUT ROWID`, inline `INTEGER PRIMARY KEY DESC`, and composite PKs need ordinary column handling. Preserve SQLite nullable PK semantics outside rowid aliases and declared NOT NULL. Legacy hand-built `ColumnInfo.is_rowid_alias=None` retains the old INTEGER heuristic; adapters report explicit booleans. Partial UNIQUE indexes retain `IndexInfo.is_partial=True` and do not imply unconditional UNIQUE; the database enforces applicable rows at insertion. Resolve SQLite table aliases using ASCII-only matching before generation; PostgreSQL names remain exact. Literal CHECK conjunctions (including separate CHECK declarations) intersect their domains. The parser preserves strict numeric boundaries regardless of literal spelling; integer/float generator adaptation applies the correct rounding. User numeric constraints and full-string regex constraints are enforced before UNIQUE registration. Appends use bounded candidate key probes against existing data; retry exhaustion, including replayed seed prefixes, does not prove key-space exhaustion.

Float CHECK bounds round inward to decimal precision grid points, not simply `bound ± step`. When a Python enum intersection is empty but strings or mixed literals leave SQL affinity/collation unknown, retain the prior candidates for database validation rather than claiming an empty SQL domain. This conservative fallback does not guarantee every candidate satisfies all CHECKs.

1. **Seed handling**: Don't set provider seed in orchestrator — `DataStream.__init__` does it (`set_seed` only when `seed is not None`)
2. **Hook return values**: pluggy returns `list[result]` for non-firstresult hooks, not a single value
3. **Mimesis locale**: Use short codes (`"en"`, `"zh"`) not Faker-style (`"en_US"`, `"zh_CN"`)
4. **Memory**: Never collect all rows before writing — use `DataStream.generate()` iterator
5. **Expression timeout**: Always handle `ExpressionTimeoutError`; timeout threads can't be killed
6. **Batch transforms chain**: Last non-`None` result wins — it's not accumulative
7. **PRAGMA restore**: Must be in `finally` block or DB stays in unsafe state
8. **SQLAlchemy core dep**: `database/sqlalchemy_adapter.py` is the required adapter; `RawSQLiteAdapter` is test-only fallback
9. **Provider fallback**: `_ensure_connected()` logs a warning and falls back directly to `"base"` when the selected provider cannot load; it does not try Faker between Mimesis and Base. Base synthesizes primitive and placeholder values. The strict Web workbench separately rejects unavailable configured providers.
10. **Orchestrator is a package**: `core/orchestrator/` is a package with 4 mixin modules, not a single file. Imports should use `from sqlseed.core.orchestrator import DataOrchestrator`.
11. **db_path vs url**: Public API and CLI both support `db_path` (SQLite) and `url` (database URL) as mutually exclusive connection modes. Never pass both.
12. **AUTO-GENERATED markers**: Doc files use paired `BEGIN:AUTO-GENERATED:<name>` and `END:AUTO-GENERATED:<name>` HTML comments for automated sync verification. Don't manually edit values inside markers — run `scripts/sync_docs.py` instead.
13. **Mock self-proving trap**: Tests that mock `sqlseed.core.*` / `sqlseed.generators.*` / `sqlseed.database.*` classes (e.g., `mapper.map_column = MagicMock(return_value=...)` then `assert_called_once_with(...)`) are self-proving — the assertion merely echoes the mock setup and never verifies the actual computed `GeneratorSpec.params`. Use a real `ColumnMapper` + real `ColumnInfo` with non-None `default` (and a non-exact-match column name like `"category"`/`"rank"`) to exercise `_type_faithful_fallback` and the downstream `_adjust_*` math. Run `make mutmut` to detect self-proving tests — surviving mutants indicate the test fails to catch real behavior changes. See `tests/test_core/test_unique_adjuster.py::TestAdjustChoiceFallback` for the recommended real-schema pattern.
14. **Architecture enforcement is multi-layer**: Defense against core code corruption/drift is provided by 4 complementary mechanisms — (a) `lint-imports` (CI gate, fails fast on forbidden layer crossings), (b) `tests/test_architecture.py` (invariant tests for module location, count contracts, public API), (c) `make mutmut` (mutation testing for self-proving mock detection), (d) `tests/test_doc_sync.py` (count markers in docs match code). All 4 must pass before merge.

## Release Checklist

When preparing a new version release:

1. **uv.lock files** — There are 3 lock files, all must be in sync with their `pyproject.toml`:
   - `./uv.lock` (root)
   - `./plugins/sqlseed-ai/uv.lock`
   - `./plugins/mcp-server-sqlseed/uv.lock`

   Run `uv lock` in each directory after any `pyproject.toml` dependency change.

2. **Changelog and release notes** — Update both `CHANGELOG.md` and `CHANGELOG.zh-CN.md` with the new version number. Prepare `.github/release-notes/v<version>.md` from the [bilingual template](.github/release-notes/TEMPLATE.md), remove unused subsections in both languages, and run `python scripts/sync_release_notes.py --check`. Keep the title exactly `v<version>` and preserve version-specific compatibility and verification evidence.

3. **Tag & Release** — After pushing all commits:
   ```bash
   git tag v<version>
   git push origin v<version>
   gh release create v<version> --verify-tag --title "v<version>" --notes-file .github/release-notes/v<version>.md
   ```
   `--verify-tag` aborts if the tag does not already exist in the remote repository.

4. **CI publish** — `publish.yml` triggers on release or `workflow_dispatch` with an existing `release_tag`. It resolves the tag to a commit for testing, building and public acceptance. Inspect failed upload logs and PyPI files before retrying. For an uploader compatibility fix, merge the workflow correction and run `gh workflow run publish.yml --ref main -f release_tag=v<version>`; preserve the existing release tag, metadata validation and attestations. Core Metadata 2.5 needs PyPA publish action v1.14.2 or newer. See [the release guide](docs/releasing.md) for recovery details.

5. **Public installation acceptance** — After all five upload jobs succeed, `publish.yml` runs `verify-public` on Linux/Python 3.12. Check that job and retain its `public-pypi-acceptance` artifact with public metadata, file hashes, pip reports and real installed Core/CLI/MCP/Web SQLite results. Repeat locally with `PYTHON_BIN=python3.12 bash scripts/verify_pypi_release.sh <version>` (Linux or macOS). Inspect all five PyPI descriptions and documentation links. A local wheel test or successful upload does not replace this step; real LLM, PostgreSQL and browser acceptance require separate evidence. See [the release guide](docs/releasing.md) for preparation and validation details.

## Sibling Agent Files

`AGENTS.md` and `GEMINI.md` exist at the repo root — same project context for other AI coding tools. `GEMINI.md` is a pointer to `CLAUDE.md` (single source of truth). Module-level `AGENTS.md` files exist in each package subdirectory under `src/sqlseed/` and under each plugin's `src/` directory.

## Plugins (separate packages)

- `plugins/sqlseed-cli/` — CLI plugin (Click commands: `fill`, `preview`, `inspect`, `init`, `replay`). Has its own `pyproject.toml` and `[project.scripts] sqlseed = sqlseed_cli:main`. Contains: `main.py` (Click commands), `_utils.py` (`sanitize_table_config()`). Core `sqlseed` package has NO `[project.scripts]` — install `sqlseed-cli` to get the `sqlseed` command. Install: `pip install sqlseed-cli` (auto-pulls `sqlseed` core).
- `plugins/sqlseed-ai/` — LLM-powered schema analysis with long-term Gemma 4 model and protocol support through configured backends. Has its own `pyproject.toml`. Contains: `analyzer/` (Layer 6 package: LLM table-level analysis with streaming/tool-calling submodules — `_caller.py`, `_streaming.py`, `_tool_calling.py` [protocol-based: `gemma4`/`openai`/`none`], `_context.py`, `_json_parser.py`), `contracts/` + `validator/` + `repair/` + `healer/` + `auto_heal/` (Layers 1-5 of the v4 contract-driven self-healing architecture — see [v4 Contract-Driven Self-Healing (sqlseed-ai)](#v4-contract-driven-self-healing-sqlseed-ai) above), `refiner.py` (self-correction loop; delegates Rule #14 param stripping to v4 `REPAIR_STRATEGIES["normalize_params"]`), `ai_mediator.py` (AI-specific mediation — `apply_ai_suggestions()` moved from core in Phase C), `config.py` (`AIConfig` with `tool_calling_protocol: Literal["gemma4", "openai", "none"]` field added in Phase E, multi-backend support; `use_staged_pipeline` field removed in Phase 4 zero-rot cleanup), `errors.py` (error summary), `exceptions.py` (structured exception types), `examples.py` (few-shot), `_client.py` (API client), `_json_utils.py` (JSON parsing), `_model_selector.py` (Gemma 4 model selection), `_hardware.py` (cross-platform RAM/GPU detection), `_prompts.py` (3-tier prompt system), `_tools.py` (`GEMMA_TOOLS` for native function calling), `cli/` (`ai_commands.py` — 3 commands injected into `sqlseed` CLI via entry_points: `ai-suggest` [per-table LLM analysis with `--auto-heal` flag], `ai-analyze` [default v4 AutoHealOrchestrator path for full/partial DB], `auto-heal` [standalone repair of existing YAML configs]; `--staged-pipeline` flag removed in Phase 4), `mcp.py` (AI MCP server: `sqlseed_ai_generate_yaml`, `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, `sqlseed_list_gemma_models`; install with `pip install "sqlseed-ai[mcp]"`). Deleted in Phase 4 zero-rot cleanup: `staged_analyzer.py`, `schema_analyzer.py`, `stage_relevance.py`, `dependency_resolver.py`, `_stage_prompts.py`, `repair/legacy_bridge.py`. Install: `pip install sqlseed-ai` (depends on `sqlseed-cli`).
- `plugins/sqlseed-web/` — Standalone FastAPI workbench with wheel-bundled static assets and optional AI services. `sqlseed-web` starts its supervisor; core has no Web dependency. Installation and support boundaries: [Web guide](docs/web-workbench.md).
- `plugins/mcp-server-sqlseed/` — MCP server (FastMCP) exposing **core capabilities only** (no LLM dependency). 2 Tools (`sqlseed_generate_yaml` rule-driven via `ColumnMapper`, `sqlseed_execute_fill`). No Resources. Schema inspection delegated to third-party MCPs; AI tools moved to `sqlseed-ai[mcp]` (Phase D). Install: `pip install mcp-server-sqlseed`.

## Dependencies

**Core** (`sqlseed`): pydantic, pluggy, structlog, pyyaml, typing_extensions, simpleeval, rstr, sqlalchemy, faker, sqlglot. NOTE: `click` and `rich` are NOT core dependencies — they belong to `sqlseed-cli`.
**Optional**: mimesis (`sqlseed[mimesis]`), tqdm (`sqlseed[notebook]`), psycopg (`sqlseed[postgres]`), sqlseed-cli (`sqlseed[cli]` — convenience alias that pulls the CLI plugin)
**Plugin: sqlseed-cli**: click, rich (depends on `sqlseed` core)
**Plugin: sqlseed-ai**: openai, httpx, networkx (depends on Core and `sqlseed-cli` for CLI entry point injection)
**Plugin: mcp-server-sqlseed**: mcp (depends on `sqlseed` core)
**App: sqlseed-web**: fastapi, uvicorn, pyyaml, packaging (depends on Core; optional `[ai]` extra adds `sqlseed-ai`)
**Dev**: pytest, pytest-cov, pytest-asyncio, pytest-benchmark, ruff, mypy, pre-commit, testcontainers, tqdm, psycopg, sqlseed-cli
