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
- **`core/mapper.py`** — `ColumnMapper` with 9-level strategy chain (L1: autoincrement PK → L2: user config → L3: exact match (custom + built-in) → L4: default value / nullability → L5: pattern match (custom + built-in) → L6: CamelCase→snake_case exact retry → L7: snake_case pattern retry → L8: nullable fallback → L9: type fallback). <!-- BEGIN:AUTO-GENERATED:exact-match-rule-count -->76<!-- END:AUTO-GENERATED:exact-match-rule-count --> exact rules, <!-- BEGIN:AUTO-GENERATED:pattern-match-rule-count -->29<!-- END:AUTO-GENERATED:pattern-match-rule-count --> regex patterns.
- **`core/schema.py`** — `SchemaInferrer` reads database schema via adapter. Methods: `get_column_info()`, `detect_unique_columns()`, `get_index_info()`, `get_sample_data()`, `profile_column_distribution()`.
- **`core/relation.py`** — `RelationResolver` + `SharedPool` for cross-table FK integrity. Implicit associations via name matching, explicit via `ColumnAssociation` config. `topological_sort()` for multi-table fill ordering — uses Kahn's algorithm with graceful cycle-breaking (logs a warning and picks the first table in input order to break circular FK dependencies, e.g., `branches↔employees`; does NOT raise `ValueError`).
- **`core/column_dag.py`** — Topological sort for `derive_from` column dependencies.
- **`core/expression.py`** — `ExpressionEngine` using `simpleeval`. Timeout via thread (5s default). `ExpressionTimeoutError` on timeout. 26 whitelisted functions in `SAFE_FUNCTIONS`.
- **`core/constraints.py`** — `ConstraintSolver` for UNIQUE enforcement with backtracking. Supports probabilistic mode (SHA256 hash-based) for >100K rows.
- **`core/enrichment.py`** — Local enum detection + enrichment (no AI logic; stays entirely in core). Detects enum columns from existing data distribution and applies local column-mapping enrichment. AI-suggested mappings are applied via the `sqlseed_apply_ai_suggestions` pluggy hook (implemented in `sqlseed-ai`).
- **`core/unique_adjuster.py`** — Post-generation UNIQUE constraint adjustment.
- **`core/plugin_mediator.py`** — Bridges plugins and core (not direct calls). Generic methods only: `apply_batch_transforms()`, `apply_template_pool()`. AI-specific `apply_ai_suggestions()` was moved to `plugins/sqlseed-ai/` (Phase C) and is invoked via the `sqlseed_apply_ai_suggestions` pluggy hook.
- **`core/transform.py`** — Row/batch transform pipeline. `load_transform(path)` loads user transform scripts.
- **`core/result.py`** — `GenerationResult` dataclass for generation results (table_name, count, elapsed, rows_per_second, batch_count, errors).
- **`generators/`** — `DataProvider` protocol: `name`, `set_locale`, `set_seed`, `generate(type_name, **params)`. 35 generator types dispatched via `GeneratorDispatchMixin.GENERATOR_MAP`. Three providers: `BaseProvider` (type-routing only, no real data), `FakerProvider` (required, standard), `MimesisProvider` (optional, high-performance).
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

### v4 Contract-Driven Self-Healing (sqlseed-ai)

The `sqlseed-ai` plugin uses the **v4 contract-driven self-healing architecture** as the default and only schema-analysis path. The legacy `Stage3Validator` (36 numbered rules), `SchemaSemanticAnalyzer`, and `StagedSchemaAnalyzer` were deleted in Phase 4 zero-rot cleanup — no dual-track system, no deprecated flags, no transitional bridges.

v4 is a 6-layer pipeline built on the open-closed principle: core code (Registry + Validator + Executor) is closed; rules are open for extension via the `REPAIR_STRATEGIES` dict.

- **Layer 1 — `contracts/`**: Sparse contract matrix + resolver. `ContractViolation` defines a single bad generator/type/constraints combination; `ContractResolver` merges builtin + learned violations with specificity-priority matching. The matrix is a *closed set* — only known-bad combinations are listed; unlisted combinations default to COMPATIBLE. `builtin_violations.py` ships the seed violations; `registry.py` exposes the lookup API.
- **Layer 2 — `validator/`**: `FastValidator` (in `main.py`) orchestrates five components: `SingleColumnValidator` (2a: per-column contract + cardinality), `CrossColumnValidator` (2b: FK integrity + derive_from DAG cycle detection), `DialectErrorParser` (Defense 3: normalize DBAPI exceptions to `ViolationReport`), `ShadowFKScanner` (Section 14.3: localize SQLite FK violation column), and `CompositeFKCoordinator` (multi-column FK). `schema_snapshot.py` records `schema_hash` at startup for optimistic-lock re-check at write time (Defense 8). `models.py` defines `ConstraintType`, `ViolationReport`, `ValidationResult`.
- **Layer 3 — `repair/`**: Stateless repair engine. Each strategy is a pure function `RepairFn = Callable[[dict, ViolationReport, dict], dict]` registered in `REPAIR_STRATEGIES`. `strategies.py` ships the canonical strategies — notably `normalize_params` (v4 replacement for legacy Rule #14: strips params not in `_GENERATOR_PARAM_WHITELIST` for ALL generators, 36 entries aligned with `base_provider.py` signatures), `coerce_int_float` (legacy Rule #26: `random_float` → `random_int` for INTEGER columns), plus derive_from cleanup, date-column generator fixes, and CHECK-chain mirroring. `executor.py` applies strategies by `fix_hint` dispatch; `pipeline.py` chains them.
- **Layer 4 — `healer/`**: 4-level LLM heal architecture with failure-type-aware routing. `orchestrator.py` (`HealOrchestrator`) coordinates 4-level degradation: Level 1 (subgraph) → Level 2 (column) → Level 3 (compact) → Level 4 (deterministic degrade). `context_detector.py` (`ContextWindowDetector`) dynamically detects model context window size (priority: `AIConfig.max_context_tokens` → model map → default 4096) and pre-judges whether to skip Level 1 (skip if token estimate > 60% of context window). `failure_classifier.py` (`FailureClassifier`) classifies LLM failures into 6 types (`CONTEXT_OVERFLOW`, `EMPTY_RESPONSE`, `JSON_FORMAT`, `SEMANTIC`, `NETWORK`, `UNKNOWN`) for routing decisions. `level1_subgraph_healer.py` (`Level1SubgraphHealer`) sends the entire subgraph to the LLM (default path). `level2_column_healer.py` (`Level2ColumnHealer`) sends only the target column + complete dependency set (CHECK constraints, derive_from sources, cross-column refs, FK info) — information boundary optimization for context overflow. `level3_compact_healer.py` (`Level3CompactHealer`) uses compact/ultra-compact prompts + JSON repair for format errors. `degrader.py` (`ProgressiveDegrader`) is the deterministic fallback (unchanged). `oscillation.py` detects repeated failures (same error type reset on type change). `subgraph.py` (`SubgraphSplitter`) does Tarjan SCC + megacluster breaking (Defenses 2 + 6). `post_repair.py` (`BrokenEdgeAligner`) repairs broken FK edges. `diff_learner.py` persists learned violations back to Layer 1. `_client.py` provides the shared `LLMClient` protocol + `OpenAICompatAdapter`. Routing: `CONTEXT_OVERFLOW`/`EMPTY_RESPONSE` → Level 2; `JSON_FORMAT` → Level 3 (skip Level 2); `SEMANTIC` → Level 4 (skip Level 2/3); `NETWORK` → raise exception. `Layer4Coordinator` and `LLMHealer` were deleted (replaced by the 4-level architecture).
- **Layer 5 — `auto_heal/`**: `AutoHealOrchestrator` (in `orchestrator.py`) is the top-level entry point for `ai-analyze` (default v4 path), `ai-suggest --auto-heal`, and the standalone `auto-heal` command. Pipeline: SchemaSnapshot → SubgraphSplitter → per-subgraph (Layer 2 validate → Layer 3 repair → Layer 4 heal) → BrokenEdgeAligner → optimistic-lock schema_hash re-check → emit YAML. `time_budget.py` (`TimeBudgetController`) enforces wall-clock budget. The `_build_subgraph_config()` method performs deterministic CHECK-constraint inference before any LLM call: `_parse_single_column_check()` handles LENGTH()/IN/BETWEEN/range patterns (including mixed `> AND <=` and `>= AND <`, `col != 0` non-zero constraint, plus float exclusive bounds `col > X` / `col < Y` / `col > X AND col <= Y` / `col > X AND col < Y` / `col >= X AND col < Y` with 0.01 epsilon to avoid generating the boundary value, plus `col IS NULL OR <inner_expr>` prefix stripping that peels off the optional NULL branch before parsing the inner expression with the existing patterns), while `_infer_cross_column_config()` handles 50 cross-column patterns (col >= other, col > other, col <= other, col < other, col != other, col >= col1 * col2, col >= col2 * CONSTANT [Pattern 7b, column-times-literal-constant lower bound — derive_from col2, expression `value * CONSTANT`], col = col1 (+|-|*) col2, col = col1 + col2 + col3, col = abs(col1) (+|-|*) col2, col = col1 (+|-|*) abs(col2), col = abs(col1) * abs(col2), col = abs(col1), col IS NULL OR col (>=|>|<=|<) other [Pattern 1, all 4 operators + date/float/int types], col IS NULL OR other IS NULL OR col (>=|>|<=|<) other [Pattern 1b, 3-way OR with NULL escape for both columns — None-guard expression prevents TypeError when source col is None; pre-loop scan ensures Pattern 1b is checked before Pattern 1 across ALL constraints, preventing 2-way OR from shadowing 3-way OR; lower-bound-aware: when the upper-bound branch (<= or <) is selected, scans all constraints for a sibling `col IS NULL OR col (>=|>) other_col2` pattern and wraps the expression with `max(result, row['other_col2'])` to enforce both bounds simultaneously (e.g., revoked_at <= expires_at AND revoked_at >= created_at — derive_from expires_at, `max(value - timedelta(...), row['created_at'])`)], col >= X AND col <= other_col, col >= other_col AND col <= Y, col > X AND col < other_col, col > other_col AND col < Y, col != VALUE OR other_col = VALUE2, col1 + col2 = col reverse-sum, col = VALUE OR other_col < col2 OR other_col > col3 range-membership, col = (col1 + col2 [+ col3]) / N average [Pattern 21, int() wrapped for INTEGER columns to match SQLite integer-division CHECK semantics], col <= col2 * CONSTANT percentage upper bound [Pattern 22], col >= col2 * CONST1 AND col <= col2 * CONST2 [Pattern 22c, dual multiplier bounds across two CHECKs — cross-constraint scan before per-constraint loop; derive_from col2, expression `value * random_float(CONST1, CONST2)`], col = VALUE OR col1 < X OR col2 < X [OR col3 < X] multi-column threshold [Pattern 23, val/opposite swapped to satisfy both OR-form and AND-form dual CHECKs], col = VALUE OR col (>|>=|<|<=) other_col [Pattern 24, conditional comparison — 50% VALUE, 50% satisfying the inequality], col1 != VALUE OR col (>|>=|<|<=) other_col [Pattern 24b, inequality-first variant of Pattern 24 — derive_from other_col, comparison-satisfying value when cond_col == VALUE, else 50% compliant/50% safe zero; cross-constraint cap: when col <= other_col also exists, uses exact equality `value` to satisfy both >= and <=], col = col1 * col2 + col3 [Pattern 25, multiplication + addition chain], col = VALUE OR other_col IN ('a','b','c') [Pattern 26, conditional enum — col set to non-VALUE when other_col is in the set], col1 != VALUE OR col IN ('a','b','c') [Pattern 26b, inequality-first variant of Pattern 26 — derive_from cond_col, random set value when cond_col == VALUE, else first set value], col1 != VALUE OR col = 'V1' OR col = 'V2' [Pattern 26c, explicit OR-equality variant of Pattern 26b — handles `col = 'V1' OR col = 'V2'` syntax instead of IN()], other_col = 'V1' AND col OP1 X1 OR other_col = 'V2' AND col OP2 X2 [OR ...] [Pattern 27, N-way conditional range — nested ternary picks per-clause random range], other_col != VALUE OR col > 0 [Pattern 28, conditional requirement — col set to positive random when other_col == VALUE, else 0], col1 != INTEGER_VALUE OR col > X [Pattern 28b, integer-value variant of Pattern 28 — derive_from col1, positive random when col1 == INT_VALUE, else 0], col = col1 (+|-) col2 (+|-) col3 [Pattern 29, three-column mixed arithmetic chain — derive_from col1, reference col2/col3 via row dict], col1 != VALUE OR col IS NULL [Pattern 30, conditional NULL — FK columns return None for BOTH branches to avoid FK violations; non-FK columns return 0/0.0], col1 = VALUE OR col IS NOT NULL [Pattern 30b, reverse of Pattern 30 — when col1 != VALUE, col must be non-NULL; FK columns use 1 (first autoincrement id), non-FK columns use 0/0.0], col1 != VALUE OR col = VALUE2 [Pattern 31, conditional equality — col set to VALUE2 when col1 == VALUE, else safe random; range-aware: scans all constraints for col >= X AND col <= Y to bound the random branch], col >= X AND col <= col2 * CONSTANT [Pattern 22b, compound range with multiplier upper bound — derive_from col2, max(X, value * factor)], (col1 = VALUE AND col > X) OR (col1 IN (...) AND col IS NULL) [Pattern 32, conditional value/NULL — col positive random when col1 == VALUE, NULL when col1 in other set], (col1 IN (...) AND col = col2 + col3) OR (col1 IN (...) AND col = col2 - col3) [Pattern 33, conditional arithmetic by type — derive_from col2, op selected by col1's type set], col1 != VALUE OR col2 (<|<=) X [Pattern 34, conditional upper bound — max_value set to X or X-epsilon; min_value preserved from single-column CHECK via _infer_from_check_constraints merge], col1 != INTEGER_VALUE OR col (<|<=) X [Pattern 34b, integer-value variant of Pattern 34 — same max_value logic, accepts unquoted integer VALUE], col1 IN (...) OR col IS NULL [Pattern 35, conditional NULL with IN set — date columns get null_ratio=1.0; non-date columns get derive_from with None for non-matching values], other_col = 'V1' AND col (>=|>) X1 AND col (<|<=) Y1 OR other_col = 'V2' AND col (>=|>) X2 AND col (<|<=) Y2 [OR ...] [Pattern 36, N-way conditional range with dual bounds — each clause has both a lower and upper literal bound; nested ternary picks per-clause random_int/random_float range], multiple `col1 != VALUE_i OR col OP_i X_i` on same column [Pattern 37, multi-conditional cross-column — when 2+ separate CHECK constraints constrain the SAME target column based on the SAME enum column's value; derive_from col1, nested ternary with a branch per VALUE_i, default branch for unmatched enum values], col = (col1 + col2) * (CONST - col3) [Pattern 38, complex arithmetic — derive_from col1, expression `(value + row['col2']) * (CONST - row['col3'])`], col1 IS NULL OR col <= col2 + col3 [Pattern 39, compound addition upper bound — derive_from col2, None-guard when value is None, else `(value + row['col3']) * random_float(0.0, 1.0)`], col1 = VALUE OR col2 IS NOT NULL where col2 is self-ref FK [Pattern 40, self-ref FK conditional equality — pre-loop scan; when col2 is always NULL (self-ref FK), col1 must be VALUE; returns choice generator with only VALUE], col (>=|>|<=|<) DATE(other_col) [Pattern 41, DATE() function wrapper — standalone comparison with DATE() coercion; strips wrapper to extract column name, then treats like Pattern 2/3/8]). Constraint sorting: conditional CHECKs (with OR) are evaluated BEFORE range CHECKs (with AND); within conditional CHECKs, IN-based patterns (Pattern 35) are prioritized over IS NULL OR patterns (Pattern 1) to ensure the more restrictive NULL constraint wins. Multi-CHECK merging: `_infer_from_check_constraints` iterates ALL matching single-column CHECKs and merges numeric/length bounds (min_value takes MAX, max_value takes MIN, type promotion int→float), rather than returning on the first match — fixing the case where `col >= 0` and `col <= 1000` are two separate CHECK constraints. FK column awareness: `_build_subgraph_config` extracts FK column names from `snapshot.tables[t].foreign_keys` and passes them to `_infer_cross_column_config` so Pattern 30 can return None (not 0) for FK columns. Step 5.5 in `run()` applies post-LLM safety nets: template-string-in-generator repair (LLM sometimes puts `'NAME-{sequence:04d}'` in the `generator` field instead of using `generator: template`), param re-inference from CHECK constraints when the LLM strips them (e.g., `latitude >= -90.0 AND latitude <= 90.0` → min_value/max_value), missing-generator inference from params (min_length→string, choices→choice, etc.), `?` placeholder normalization (LLM emits `generator: '?'` for undecided columns; cleared to None so missing-generator repair takes over), cross-column derive_from restoration (when the LLM rewrites a column that had `derive_from` from `_build_subgraph_config` Step 1, re-applies `_infer_cross_column_config` to restore the cross-column relation — e.g., `closed_at` getting `derive_from: opened_at` instead of a plain `datetime` generator that would violate `closed_at IS NULL OR closed_at >= opened_at`), and `_strip_invalid_params` to remove params not in the generator's whitelist. LIKE constraint handling: `_like_to_regex()` converts SQL LIKE patterns to anchored regex (preserving literal positions via per-character iteration — e.g., `__:__` → `^[A-Za-z0-9]{2}:[A-Za-z0-9]{2}$`, `#______` → `^\#[A-Za-z0-9]{6}$`); `_has_like_constraint()` checks if a column has a LIKE CHECK constraint. In `_infer_cross_column_config()`, a LIKE guard returns None immediately when `col_name` has a LIKE constraint (formatted string columns like `start_time LIKE '__:__'` store "HH:MM" strings, not real datetimes/numbers — any arithmetic derive_from would fail at fill time with `TypeError: can only concatenate str (not X) to str`); constraints where any `other_col` has a LIKE constraint are also skipped. The arithmetic-on-string safety net in Step 5.5 strips `derive_from` when the column or source column has a LIKE constraint and the expression contains arithmetic (`value +`, `value -`, `value *`, `value/`, `timedelta`). The re-infer params path overrides the generator with `pattern` (from `_infer_from_check_constraints` LIKE → regex logic) when the column has a LIKE constraint — only a `pattern` generator can guarantee the format.
- **Layer 6 — `analyzer/`**: LLM table-level analysis with streaming/tool-calling submodules (`_caller.py`, `_streaming.py`, `_tool_calling.py` [protocol-based: `gemma4`/`openai`/`none`], `_context.py`, `_json_parser.py`). Used by the non-auto-heal `ai-suggest` path.

The legacy `Stage3Validator` rules are migrated to v4 strategies as follows (non-exhaustive): Rule #14 → `normalize_params`; Rule #22 → deferred `_has_date_year_range` check (runs after derive_from processing); Rule #26 → `coerce_int_float`; Rule #35 → derive_from cleanup for non-timedelta date expressions; Rule #36 → date-column generator coercion. The full migration coverage matrix is in [`docs/superpowers/plans/v4_coverage_matrix.md`](./docs/superpowers/plans/v4_coverage_matrix.md).

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
- `plugins/sqlseed-ai/` — LLM-powered schema analysis via Gemma 4 (long-term LLM backend, NOT competition-only). Has its own `pyproject.toml`. Contains: `analyzer/` (Layer 6 package: LLM table-level analysis with streaming/tool-calling submodules — `_caller.py`, `_streaming.py`, `_tool_calling.py` [protocol-based: `gemma4`/`openai`/`none`], `_context.py`, `_json_parser.py`), `contracts/` + `validator/` + `repair/` + `healer/` + `auto_heal/` (Layers 1-5 of the v4 contract-driven self-healing architecture — see [v4 Contract-Driven Self-Healing (sqlseed-ai)](#v4-contract-driven-self-healing-sqlseed-ai) above), `refiner.py` (self-correction loop; delegates Rule #14 param stripping to v4 `REPAIR_STRATEGIES["normalize_params"]`), `ai_mediator.py` (AI-specific mediation — `apply_ai_suggestions()` moved from core in Phase C), `config.py` (`AIConfig` with `tool_calling_protocol: Literal["gemma4", "openai", "none"]` field added in Phase E, multi-backend support; `use_staged_pipeline` field removed in Phase 4 zero-rot cleanup), `errors.py` (error summary), `exceptions.py` (structured exception types), `examples.py` (few-shot), `_client.py` (API client), `_json_utils.py` (JSON parsing), `_model_selector.py` (Gemma 4 model selection), `_hardware.py` (cross-platform RAM/GPU detection), `_prompts.py` (3-tier prompt system), `_tools.py` (`GEMMA_TOOLS` for native function calling), `cli/` (`ai_commands.py` — 3 commands injected into `sqlseed` CLI via entry_points: `ai-suggest` [per-table LLM analysis with `--auto-heal` flag], `ai-analyze` [default v4 AutoHealOrchestrator path for full/partial DB], `auto-heal` [standalone repair of existing YAML configs]; `--staged-pipeline` flag removed in Phase 4), `mcp.py` (AI MCP server: `sqlseed_ai_generate_yaml`, `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, `sqlseed_list_gemma_models`; install with `pip install "sqlseed-ai[mcp]"`). Deleted in Phase 4 zero-rot cleanup: `staged_analyzer.py`, `schema_analyzer.py`, `stage_relevance.py`, `dependency_resolver.py`, `_stage_prompts.py`, `repair/legacy_bridge.py`. Install: `pip install sqlseed-ai` (depends on `sqlseed-cli`).
- `plugins/mcp-server-sqlseed/` — MCP server (FastMCP) exposing **core capabilities only** (no LLM dependency). 2 Tools (`sqlseed_generate_yaml` rule-driven via `ColumnMapper`, `sqlseed_execute_fill`). No Resources. Schema inspection delegated to third-party MCPs; AI tools moved to `sqlseed-ai[mcp]` (Phase D). Install: `pip install mcp-server-sqlseed`.

## Dependencies

**Core** (`sqlseed`): pydantic, pluggy, structlog, pyyaml, typing_extensions, simpleeval, rstr, sqlalchemy, faker. NOTE: `click` and `rich` are NOT core dependencies — they belong to `sqlseed-cli`.
**Optional**: mimesis (`sqlseed[mimesis]`), tqdm (`sqlseed[notebook]`), psycopg (`sqlseed[postgres]`), sqlseed-cli (`sqlseed[cli]` — convenience alias that pulls the CLI plugin)
**Plugin: sqlseed-cli**: click, rich (depends on `sqlseed` core)
**Plugin: sqlseed-ai**: openai, httpx (depends on `sqlseed-cli` for CLI entry point injection)
**Plugin: mcp-server-sqlseed**: mcp (depends on `sqlseed` core)
**Dev**: pytest, pytest-cov, pytest-asyncio, pytest-benchmark, ruff, mypy, pre-commit, testcontainers, tqdm, psycopg, sqlseed-cli
