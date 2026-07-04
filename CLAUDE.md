# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is sqlseed

Python 3.10+ declarative multi-database test data generation toolkit. Single API call infers schema, picks generators via 9-level column mapping, streams data in batches, and maintains FK integrity across tables. Supports SQLite (default) and PostgreSQL via SQLAlchemy. MySQL was removed (deferred until PostgreSQL is fully validated). Optional plugins add CLI (`sqlseed-cli`), AI-powered schema analysis (`sqlseed-ai` via Gemma 4 long-term LLM backend), and MCP server (`mcp-server-sqlseed`).

**Stack**: hatchling + hatch-vcs build, ruff lint, mypy strict, pytest. License: AGPL-3.0-or-later.

**Architecture**: 4 independent packages — `sqlseed` (core, offline Python API), `sqlseed-cli` (CLI plugin), `sqlseed-ai` (AI plugin), `mcp-server-sqlseed` (MCP plugin). See [ARCHITECTURE.md](./ARCHITECTURE.md) for the authoritative architecture reference.

## Quick Start Commands

```bash
# Install core in dev mode (all optional deps + dev tools)
pip install -e ".[dev,all]"

# Install plugins in editable mode (for plugin development)
pip install -e "./plugins/sqlseed-cli"
pip install -e "./plugins/sqlseed-ai"
pip install -e "./plugins/mcp-server-sqlseed"

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
plugins/mcp-server-sqlseed/ ─┘                    database/
                                                  plugins/
                                                  config/

_utils/ → (no internal deps, used by all layers)
```

Core (`sqlseed`) has **no CLI, no AI, no MCP code** — these are all plugins. Core never depends on `click`, `rich`, `openai`, or `mcp`.

**Never**: `generators` → `core`, `database` → `core`, `_utils` → any upper layer, `core` → any plugin.

### Key Modules

- **`core/orchestrator/`** — Package (refactored from single file). `DataOrchestrator` is the central coordinator, composed via multiple inheritance from 4 mixins + 1 shared data module:
  - `_common.py` — Shared dataclasses (not a mixin): `CoreCtx` (db, schema, mapper, relation, shared_pool), `ExtCtx` (registry, plugins, mediator, enrichment, unique_adjuster, metrics). Helper: `_is_db_url()`.
  - `_connection.py` — `ConnectionMixin`: lifecycle (`__init__`, `_ensure_connected`, `close`), adapter creation, property accessors for all `_core`/`_ext` fields, context manager protocol, `from_config()` classmethod.
  - `_specs.py` — `SpecResolverMixin`: `_resolve_specs()` (schema inference → column mapping → enrichment → unique adjustment → FK resolution), `_build_stream()`, `_prepare_specs()` (AI suggestion/template pool application), `_resolve_user_configs()`.
  - `_generation.py` — `GenerationMixin`: `_generate_and_insert_batches()`, `fill_table()` (main entry point), `preview_table()`. `fill = fill_table` alias.
  - `_query.py` — `QueryMixin`: `get_schema_context()`, `get_column_mapping()`, `get_column_names()`, `get_skippable_columns()`, `get_topological_table_order()`, `get_table_names()`, `get_column_info()`, `get_foreign_keys()`, `get_row_count()`, `execute()`, `query()`, `fetch_one()`, `report()`, `map_column()`.
- **`core/mapper.py`** — `ColumnMapper` with 9-level strategy chain (L1: autoincrement PK → L2: user config → L3: exact match (custom + built-in) → L4: default value / nullability → L5: pattern match (custom + built-in) → L6: CamelCase→snake_case exact retry → L7: snake_case pattern retry → L8: nullable fallback → L9: type fallback). <!-- BEGIN:AUTO-GENERATED:exact-match-rule-count -->75<!-- END:AUTO-GENERATED:exact-match-rule-count --> exact rules, <!-- BEGIN:AUTO-GENERATED:pattern-match-rule-count -->29<!-- END:AUTO-GENERATED:pattern-match-rule-count --> regex patterns.
- **`core/schema.py`** — `SchemaInferrer` reads database schema via adapter. Methods: `get_column_info()`, `detect_unique_columns()`, `get_index_info()`, `get_sample_data()`, `profile_column_distribution()`.
- **`core/relation.py`** — `RelationResolver` + `SharedPool` for cross-table FK integrity. Implicit associations via name matching, explicit via `ColumnAssociation` config. `topological_sort()` for multi-table fill ordering.
- **`core/column_dag.py`** — Topological sort for `derive_from` column dependencies.
- **`core/expression.py`** — `ExpressionEngine` using `simpleeval`. Timeout via thread (5s default). `ExpressionTimeoutError` on timeout. 26 whitelisted functions in `SAFE_FUNCTIONS`.
- **`core/constraints.py`** — `ConstraintSolver` for UNIQUE enforcement with backtracking. Supports probabilistic mode (SHA256 hash-based) for >100K rows.
- **`core/enrichment.py`** — Local enum detection + enrichment (no AI logic; stays entirely in core). Detects enum columns from existing data distribution and applies local column-mapping enrichment. AI-suggested mappings are applied via the `sqlseed_apply_ai_suggestions` pluggy hook (implemented in `sqlseed-ai`).
- **`core/unique_adjuster.py`** — Post-generation UNIQUE constraint adjustment.
- **`core/plugin_mediator.py`** — Bridges plugins and core (not direct calls). Generic methods only: `apply_batch_transforms()`, `apply_template_pool()`. AI-specific `apply_ai_suggestions()` was moved to `plugins/sqlseed-ai/` (Phase C) and is invoked via the `sqlseed_apply_ai_suggestions` pluggy hook.
- **`core/transform.py`** — Row/batch transform pipeline. `load_transform(path)` loads user transform scripts.
- **`core/result.py`** — `GenerationResult` dataclass for generation results (table_name, count, elapsed, rows_per_second, batch_count, errors).
- **`generators/`** — `DataProvider` protocol: `name`, `set_locale`, `set_seed`, `generate(type_name, **params)`. 34 generator types dispatched via `GeneratorDispatchMixin.GENERATOR_MAP`. Three providers: `BaseProvider` (type-routing only, no real data), `FakerProvider` (required, standard), `MimesisProvider` (optional, high-performance).
- **`database/`** — `DatabaseAdapter` protocol with `SQLAlchemyAdapter` (required core dependency, supports SQLite/PostgreSQL via SQLAlchemy) and `RawSQLiteAdapter` (test-only fallback). Dialect abstraction in `_dialect.py`, type normalization in `_type_normalizer.py`, bulk write optimization in `_bulk_optimizer.py`. Additional: `_base_adapter.py` (shared base), `_helpers.py` (batch insert helpers), `optimizer.py` (PRAGMA optimization), `_sqlite_schema.py` (SQLite-specific autoincrement detection via `sqlite_master`). MySQL support was removed (Phase A).
- **`plugins/`** — 12 pluggy hooks. `PluginManager` + `PluginMediator` bridge plugins and core. This is the plugin **infrastructure** (hookspecs + manager); actual plugin implementations live in `plugins/sqlseed-cli/`, `plugins/sqlseed-ai/`, `plugins/mcp-server-sqlseed/`.
- **`config/`** — Pydantic models (`GeneratorConfig`, `TableConfig`, `ColumnConfig`, `ColumnConstraintsConfig`, `ColumnAssociation`, `ProviderType`), YAML/JSON loader, `SnapshotManager` (save/load/list_snapshots; CLI `replay` command uses `SnapshotManager.load()` + `DataOrchestrator.from_config()`).
- **`_utils/paths.py`** — Platform-aware cache directory resolution (`get_cache_dir()`). Supports macOS/Linux/Windows, overridable via `SQLSEED_CACHE_DIR` env var.
- **`_utils/sql_safe.py`** — SQL identifier quoting (`quote_identifier()`), table name validation (`validate_table_name()`), insert SQL generation (`build_insert_sql()`).
- **`_utils/progress.py`** — Progress bar abstraction (`ProgressBackend` protocol) with Rich and tqdm backends, factory `create_progress()`.
- **`_utils/metrics.py`** — `MetricsCollector` for performance metrics.
- **`_utils/logger.py`** — Structured logging via `structlog`. `get_logger()`, `configure_logging()`.
- **`plugins/sqlseed-ai/staged_analyzer.py`** — `StagedSchemaAnalyzer` (3-stage LtM pipeline entry point, flag-gated by `AIConfig.use_staged_pipeline`) and `Stage3Validator` (rule-based validation: Rule #14 strips invalid generator params, Rule #26 coerces `random_float` → `random_int` for INTEGER columns). See [Staged Pipeline](#staged-pipeline-sqlseed-ai) below.
- **`plugins/sqlseed-ai/schema_analyzer.py`** — Legacy `SchemaSemanticAnalyzer` (single-shot LLM path). `apply_auto_fix_rules_1_13()` public function shared with the staged path.

> **Note**: The `cli/` directory no longer exists in `src/sqlseed/` — CLI code moved to `plugins/sqlseed-cli/` (Phase B). Core `pyproject.toml` has no `[project.scripts]` entry.

### Public API (`src/sqlseed/__init__.py`)

| Function | Purpose |
|----------|---------|
| `fill(db_path, *, url, table, count, ...)` | Single table zero-config fill |
| `connect(db_path, *, url, ...)` | Returns `DataOrchestrator` context manager |
| `preview(db_path, *, url, table, count, ...)` | Preview data without writing |
| `fill_from_config(config_path)` | Batch fill from YAML/JSON config |
| `load_config(path)` | Load config as `GeneratorConfig` |

All public API functions accept `db_path` (SQLite file) and `url` (database URL) as mutually exclusive connection modes.

### Config Model Hierarchy

`GeneratorConfig` → `list[TableConfig]` → `list[ColumnConfig]` + `list[ColumnAssociation]`

`GeneratorConfig` has mutually exclusive `db_path` / `url` fields; `connection_target` property returns whichever is set.

`ColumnConfig` contains optional `constraints: ColumnConstraintsConfig` (unique, min_value, max_value, regex, max_retries with ge=0).

ColumnConfig supports two mutually exclusive modes (enforced by Pydantic `model_validator`):
- **Source mode**: `generator` + `params` + `null_ratio` + `provider`
- **Derived mode**: `derive_from` + `expression`

ColumnConfig also supports `faker_method`, `mimesis_method`, and `native_params` for AI-suggested native method overrides.

### Plugin Hooks (12 total)

| Hook | firstresult | When |
|------|:-----------:|------|
| `sqlseed_register_providers(registry)` | ✗ | `_ensure_connected()` |
| `sqlseed_register_column_mappers(mapper)` | ✗ | `_ensure_connected()` |
| `sqlseed_ai_analyze_table(...)` | ✓ | `sqlseed_apply_ai_suggestions()` (low-level LLM call) |
| `sqlseed_apply_ai_suggestions(...)` | ✓ | Orchestrator `_resolve_specs()` (high-level AI mediation; implemented in `sqlseed_ai.ai_mediator`) |
| `sqlseed_before_generate(table_name, count, config)` | ✗ | Before main generation loop |
| `sqlseed_after_generate(table_name, count, elapsed)` | ✗ | After generation completes |
| `sqlseed_transform_row(table_name, row)` | ✗ | Per-row (hot path) |
| `sqlseed_transform_batch(table_name, batch)` | ✗ | `apply_batch_transforms()` |
| `sqlseed_before_insert(table_name, batch_number, batch_size)` | ✗ | Before each batch write |
| `sqlseed_after_insert(table_name, batch_number, rows_inserted)` | ✗ | After each batch write |
| `sqlseed_shared_pool_loaded(table_name, shared_pool)` | ✗ | After `register_shared_pool()` |
| `sqlseed_pre_generate_templates(...)` | ✓ | `apply_template_pool()` |

### Staged Pipeline (sqlseed-ai)

The `sqlseed-ai` plugin ships two schema-analysis paths, switchable via `AIConfig.use_staged_pipeline`:

- **Legacy path** (`use_staged_pipeline=False`, default): `SchemaSemanticAnalyzer` in `schema_analyzer.py` — single-shot LLM call per table. Used by `ai-suggest` without `--staged-pipeline`.
- **Staged path** (`use_staged_pipeline=True`): `StagedSchemaAnalyzer` in `staged_analyzer.py` — 3-stage Least-to-Most (LtM) pipeline designed for small LLMs. Stages: structural features → per-column generation plan → YAML assembly + validation.

Key classes and rules:

- `StagedSchemaAnalyzer` — Entry point, flag-gated by `use_staged_pipeline`. Orchestrates the 3 stages and delegates Stage 3 validation to `Stage3Validator`.
- `Stage3Validator` — Rule-based validation applied on top of LLM output (rules #14-#19). Notable rules:
  - **Rule #14** — Parameter whitelist stripping. Removes params not accepted by the generator (e.g., `domain`/`min_length`/`example` hallucinated on `email`, which accepts no params). Also corrects the common `choice` → `choices` typo.
  - **Rule #26** — INTEGER column `random_float` → `random_int` coercion. LLMs sometimes return `random_float(0, value)` for INTEGER columns (e.g., `tasks.actual_hours INTEGER`); SQLite's dynamic typing would otherwise store fractional values. Rewrites `random_float(...)` to `random_int(...)` when the target column is INTEGER-family (INTEGER/INT/BIGINT/SMALLINT/TINYINT/MEDIUMINT).

Supporting modules:

- `stage_relevance.py` — Stage relevance scoring (selects which stages run per table).
- `dependency_resolver.py` — Column dependency resolution (orders columns within a stage).
- `_stage_prompts.py` — Stage-specific prompt templates (separate from the legacy 3-tier `_prompts.py`).

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
| `src/sqlseed/generators/_dispatch.py` | README.md, README.zh-CN.md | Generator type table (count + names) |
| `src/sqlseed/core/mapper.py` | README.md, CLAUDE.md | Exact match rule count, pattern match count |
| `src/sqlseed/core/expression.py` | README.md, README.zh-CN.md | SAFE_FUNCTIONS table (count + names) |
| `src/sqlseed/plugins/hookspecs.py` | README.md, CLAUDE.md, docs/architecture.md | Hook table (count + names) |
| `src/sqlseed/config/models.py` | docs/architecture.md, docs/architecture.zh-CN.md | Class diagrams (field names + types) |
| `plugins/sqlseed-cli/src/sqlseed_cli/main.py` | README.md, README.zh-CN.md | CLI command reference |
| `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` | README.md, README.zh-CN.md | AI CLI command reference |
| `src/sqlseed/__init__.py` | README.md, README.zh-CN.md | Public API table |

Run `pytest tests/test_doc_sync.py` to verify doc sync after changes. Uses AUTO-GENERATED markers (`<!-- BEGIN:AUTO-GENERATED:marker-name -->value<!-- END:AUTO-GENERATED:marker-name -->`) for automated count verification.

## Testing

- **Test layout** (Phase F): Core tests in `tests/`; plugin tests co-located with their plugins:
  - `tests/` — core tests (orchestrator, mapper, schema, generators, database, config, etc.)
  - `plugins/sqlseed-cli/tests/` — CLI tests (moved from `tests/` in Phase F)
  - `plugins/sqlseed-ai/tests/` — AI plugin tests (moved from `tests/` in Phase F)
  - `plugins/mcp-server-sqlseed/tests/` — MCP server tests
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
- Architecture guard tests: `tests/test_architecture.py` (13 tests verifying module boundaries, production isolation, count contracts, public API surface) — complement `lint-imports` and the `[tool.importlinter]` contracts in `pyproject.toml`.
- Mutation testing (mutmut): `make mutmut` runs mutation tests on `src/sqlseed/core/unique_adjuster.py` by default. Override with `--paths-to-mutate` and `--runner` CLI flags to test other modules. See `pyproject.toml` `[tool.mutmut]` for the baseline (49.2% survival on 2026-06-25) and `make mutmut-report` to inspect surviving mutants. **Surviving mutants indicate self-proving tests** — tests that pass because mocks returned what the author expected, not because the production code actually computes the right thing. When adding new core code or strengthening tests, run `make mutmut` and check that the survival rate does not increase.

## Critical Pitfalls

1. **Seed handling**: Don't set provider seed in orchestrator — `DataStream.__init__` does it (`set_seed` only when `seed is not None`)
2. **Hook return values**: pluggy returns `list[result]` for non-firstresult hooks, not a single value
3. **Mimesis locale**: Use short codes (`"en"`, `"zh"`) not Faker-style (`"en_US"`, `"zh_CN"`)
4. **Memory**: Never collect all rows before writing — use `DataStream.generate()` iterator
5. **Expression timeout**: Always handle `ExpressionTimeoutError`; timeout threads can't be killed
6. **Batch transforms chain**: Last non-`None` result wins — it's not accumulative
7. **PRAGMA restore**: Must be in `finally` block or DB stays in unsafe state
8. **SQLAlchemy core dep**: `database/sqlalchemy_adapter.py` is the required adapter; `RawSQLiteAdapter` is test-only fallback
9. **Provider fallback**: `_ensure_connected()` silently falls back to `"base"` on provider load failure. Provider chain: mimesis (optional, high-performance) → faker (required, standard) → base (type-routing only, no real data).
10. **Orchestrator is a package**: `core/orchestrator/` is a package with 4 mixin modules, not a single file. Imports should use `from sqlseed.core.orchestrator import DataOrchestrator`.
11. **db_path vs url**: Public API and CLI both support `db_path` (SQLite) and `url` (database URL) as mutually exclusive connection modes. Never pass both.
12. **AUTO-GENERATED markers**: Doc files use `<!-- BEGIN:AUTO-GENERATED:marker-name -->...<!-- END:AUTO-GENERATED:marker-name -->` markers for automated sync verification. Don't manually edit values inside markers — run `scripts/sync_docs.py` instead.
13. **Mock self-proving trap**: Tests that mock `sqlseed.core.*` / `sqlseed.generators.*` / `sqlseed.database.*` classes (e.g., `mapper.map_column = MagicMock(return_value=...)` then `assert_called_once_with(...)`) are self-proving — the assertion merely echoes the mock setup and never verifies the actual computed `GeneratorSpec.params`. Use a real `ColumnMapper` + real `ColumnInfo` with non-None `default` (and a non-exact-match column name like `"category"`/`"rank"`) to exercise `_type_faithful_fallback` and the downstream `_adjust_*` math. Run `make mutmut` to detect self-proving tests — surviving mutants indicate the test fails to catch real behavior changes. See `tests/test_core/test_unique_adjuster.py::TestAdjustChoiceFallback` for the recommended real-schema pattern.
14. **Architecture enforcement is multi-layer**: Defense against core code corruption/drift is provided by 4 complementary mechanisms — (a) `lint-imports` (CI gate, fails fast on forbidden layer crossings), (b) `tests/test_architecture.py` (13 invariant tests for module location, count contracts, public API), (c) `make mutmut` (mutation testing for self-proving mock detection), (d) `tests/test_doc_sync.py` (count markers in docs match code). All 4 must pass before merge.

## Release Checklist

When preparing a new version release:

1. **uv.lock files** — There are 3 lock files, all must be in sync with their `pyproject.toml`:
   - `./uv.lock` (root)
   - `./plugins/sqlseed-ai/uv.lock`
   - `./plugins/mcp-server-sqlseed/uv.lock`

   Run `uv lock` in each directory after any `pyproject.toml` dependency change.

2. **Changelog** — Update both `CHANGELOG.md` and `CHANGELOG.zh-CN.md` with the new version number.

3. **Tag & Release** — After pushing all commits:
   ```bash
   git tag v<version>
   git push origin v<version>
   gh release create v<version> --title "v<version>" --generate-notes
   ```

4. **CI publish** — `publish.yml` triggers on release or `workflow_dispatch`. If PyPI publish fails on sigstore attestation (`ChunkedEncodingError`), this is a known upstream issue ([#364](https://github.com/pypa/gh-action-pypi-publish/issues/364)) — re-run the workflow via GitHub Actions UI.

## Sibling Agent Files

`AGENTS.md` and `GEMINI.md` exist at the repo root — same project context for other AI coding tools. `GEMINI.md` is a pointer to `CLAUDE.md` (single source of truth). Module-level `AGENTS.md` files exist in each package subdirectory under `src/sqlseed/` and under each plugin's `src/` directory.

## Plugins (separate packages)

- `plugins/sqlseed-cli/` — CLI plugin (Click commands: `fill`, `preview`, `inspect`, `init`, `replay`). Has its own `pyproject.toml` and `[project.scripts] sqlseed = sqlseed_cli:main`. Contains: `main.py` (Click commands), `_utils.py` (`sanitize_table_config()`). Core `sqlseed` package has NO `[project.scripts]` — install `sqlseed-cli` to get the `sqlseed` command. Install: `pip install sqlseed-cli` (auto-pulls `sqlseed` core).
- `plugins/sqlseed-ai/` — LLM-powered schema analysis via Gemma 4 (long-term LLM backend, NOT competition-only). Has its own `pyproject.toml`. Contains: `analyzer/` (package: LLM table-level analysis with streaming/tool-calling submodules — `_caller.py`, `_streaming.py`, `_tool_calling.py` [protocol-based: `gemma4`/`openai`/`none`], `_context.py`, `_json_parser.py`), `refiner.py` (self-correction loop), `schema_analyzer.py` (legacy schema analyzer — single-shot LLM path used by `ai-suggest` without `--staged-pipeline`), `staged_analyzer.py` (3-stage LtM pipeline entry point, flag-gated by `AIConfig.use_staged_pipeline`), `stage_relevance.py` (stage relevance scoring), `dependency_resolver.py` (column dependency resolution), `_stage_prompts.py` (stage-specific prompt templates), `ai_mediator.py` (AI-specific mediation — `apply_ai_suggestions()` moved from core in Phase C), `config.py` (`AIConfig` with `tool_calling_protocol: Literal["gemma4", "openai", "none"]` field added in Phase E, multi-backend support), `errors.py` (error summary), `exceptions.py` (structured exception types), `examples.py` (few-shot), `_client.py` (API client), `_json_utils.py` (JSON parsing), `_model_selector.py` (Gemma 4 model selection), `_hardware.py` (cross-platform RAM/GPU detection), `_prompts.py` (3-tier prompt system), `_tools.py` (`GEMMA_TOOLS` for native function calling), `cli/` (`ai_commands.py` — `ai-suggest` command injected into `sqlseed` CLI via entry_points), `mcp.py` (AI MCP server: `sqlseed_ai_generate_yaml`, `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, `sqlseed_list_gemma_models`; install with `pip install "sqlseed-ai[mcp]"`). Install: `pip install sqlseed-ai` (depends on `sqlseed-cli`).
- `plugins/mcp-server-sqlseed/` — MCP server (FastMCP) exposing **core capabilities only** (no LLM dependency). 2 Tools (`sqlseed_generate_yaml` rule-driven via `ColumnMapper`, `sqlseed_execute_fill`). No Resources. Schema inspection delegated to third-party MCPs; AI tools moved to `sqlseed-ai[mcp]` (Phase D). Install: `pip install mcp-server-sqlseed`.

## Dependencies

**Core** (`sqlseed`): pydantic, pluggy, structlog, pyyaml, typing_extensions, simpleeval, rstr, sqlalchemy, faker. NOTE: `click` and `rich` are NOT core dependencies — they belong to `sqlseed-cli`.
**Optional**: mimesis (`sqlseed[mimesis]`), tqdm (`sqlseed[notebook]`), psycopg (`sqlseed[postgres]`), sqlseed-cli (`sqlseed[cli]` — convenience alias that pulls the CLI plugin)
**Plugin: sqlseed-cli**: click, rich (depends on `sqlseed` core)
**Plugin: sqlseed-ai**: openai, httpx (depends on `sqlseed-cli` for CLI entry point injection)
**Plugin: mcp-server-sqlseed**: mcp (depends on `sqlseed` core)
**Dev**: pytest, pytest-cov, pytest-asyncio, pytest-benchmark, ruff, mypy, pre-commit, testcontainers, tqdm, psycopg, sqlseed-cli
