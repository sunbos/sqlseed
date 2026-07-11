# PROJECT KNOWLEDGE BASE

**Last updated:** 2026-07-11
**Branch:** `feat/contract-driven-self-healing`

## OVERVIEW

Declarative Multi-Database test data generation toolkit. YAML/JSON config or Python API. Auto-infers schema, 9-level column mapping, 35 generators, plugin system (pluggy). Supports SQLite (default) and PostgreSQL via SQLAlchemy. MySQL removed (deferred until PostgreSQL fully validated). Gemma 4 as long-term LLM backend (protocol-based native function calling). License: **AGPL-3.0-or-later**.

**Stack**: Python 3.10+ (`requires-python = ">=3.10"`), hatchling + hatch-vcs build, ruff lint, mypy strict, pytest. CI also gates on `lint-imports` (architectural layer contracts) and `mutmut` (mutation testing).

**Architecture**: 4 independent packages — `sqlseed` (core, offline), `sqlseed-cli` (CLI plugin), `sqlseed-ai` (AI plugin), `mcp-server-sqlseed` (MCP plugin; module path is `mcp_server_sqlseed`, note the underscore). See [ARCHITECTURE.md](./ARCHITECTURE.md) for the authoritative architecture reference; [CLAUDE.md](./CLAUDE.md) has the canonical "Never/Always" rules.

**Current work**: the `sqlseed-ai` self-healing subsystem (`auto_heal/`, `healer/`, `validator/`, `repair/`, `contracts/`) — contract-driven, multi-level repair pipeline. Regression reports live in `data_quality_demo/` (r1–r7 scenarios). Do not delete these without checking.

## STRUCTURE

```
sqlseed/
├── src/sqlseed/          # Core package (no CLI/AI/MCP code)
│   ├── __init__.py       # Public API: fill, connect, fill_from_config, preview
│   ├── core/             # Orchestrator, mapper, schema, constraints, DAG, enrichment, transform
│   ├── generators/       # Data providers: base, faker, mimesis
│   ├── database/         # DB adapters: SQLAlchemy (required, SQLite+PostgreSQL), raw sqlite3 (test-only)
│   ├── plugins/          # Plugin infrastructure: hookspecs, manager, mediator
│   ├── config/           # Pydantic models, YAML loader, snapshots
│   └── _utils/           # Internal: sql_safe, metrics, progress, logger, paths
├── tests/                # Core pytest suite, conftest fixtures
├── plugins/
│   ├── sqlseed-cli/      # CLI plugin: fill, preview, inspect, init, replay (separate package)
│   ├── sqlseed-ai/       # AI plugin: LLM schema analysis + self-healing (healer/, validator/, repair/, contracts/)
│   └── mcp-server-sqlseed/  # MCP server: rule-driven YAML gen + execute_fill (no LLM)
├── data_quality_demo/    # Regression scenarios (r1–r7) + reports; scratch space, not shipped
├── scripts/              # Helper scripts (run scripts, validation harnesses)
├── docs/                 # mkdocs-material site
└── examples/             # Usage examples
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new generator | `src/sqlseed/generators/` | Create new provider; base_provider is type-routing only, real data from faker/mimesis |
| Modify column mapping | `src/sqlseed/core/mapper.py` | 9-level strategy chain |
| Add CLI command | `plugins/sqlseed-cli/src/sqlseed_cli/main.py` | Core commands (fill, preview, inspect, init, replay) |
| Add AI CLI command | `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` | 3 AI commands (ai-suggest, ai-analyze, auto-heal), injected via entry_points |
| Add plugin hook | `src/sqlseed/plugins/hookspecs.py` | pluggy hookspec |
| Modify schema inference | `src/sqlseed/core/schema.py` | SchemaInferrer class |
| Change batch insert | `src/sqlseed/database/` | SQLAlchemyAdapter (required), RawSQLiteAdapter (test-only) |
| Add test fixture | `tests/conftest.py` | tmp_db, tmp_db_with_data, unique_test_db (plugin tests re-export from here) |
| Configure AI plugin | `plugins/sqlseed-ai/` | Separate pyproject.toml, Gemma 4 multi-backend, `tool_calling_protocol` field |
| Add MCP tool | `plugins/mcp-server-sqlseed/` | FastMCP, 2 tools (generate_yaml rule-driven, execute_fill). AI tools in sqlseed-ai[mcp] |

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

## CI GATES (must pass before merge)

- `ruff check src/ tests/ plugins/` and `ruff format --check src/ tests/ plugins/`
- `mypy src/sqlseed/ plugins/` (strict on source; tests excluded)
- `pytest`
- `lint-imports` — enforces the 3 forbidden layer contracts in `pyproject.toml` `[tool.importlinter]`: generators/database must not import core; `_utils` must not import upper layers. Violations fail CI automatically instead of relying on agents reading docs.
- `mutmut` — mutation testing to catch self-proving mock-based tests. **Windows gotcha**: mutmut 3.x is not Windows-native; use `mutmut<3` and set `PYTHONUTF8=1` (see `Makefile` `mutmut` target). Default high-risk module is `unique_adjuster`.

## UNIQUE STYLES

- **Provider fallback chain**: mimesis (optional, high-performance) → faker (required, standard) → base (type-routing only, no real data)
- **AI backend fallback chain**: Google AI Studio → LM Studio → Ollama → OpenAI-compat (4 backends, no gemma4 backend)
- **Gemma 4 protocol-based tool calling**: `AIConfig.tool_calling_protocol: Literal["gemma4", "openai", "none"]` (Phase E). `GEMMA_TOOLS` shared across protocols; `resolve_tool_calling_protocol()` narrows based on backend support. Gemma4 is a long-term LLM backend (NOT competition-only).
- **Context manager pattern**: `DataOrchestrator` is a context manager
- **Plugin mediation**: `PluginMediator` bridges plugins and core (generic methods only: `apply_batch_transforms`, `apply_template_pool`). AI-specific `apply_ai_suggestions` moved to `sqlseed-ai` (Phase C), invoked via pluggy hook.
- **DAG-based column ordering**: `ColumnDAG` handles derive_from dependencies
- **SnapshotManager**: save/load/list_snapshots only; CLI `replay` uses load() + DataOrchestrator.from_config()

## AI SELF-HEALING SUBSYSTEM (`sqlseed-ai`, current branch focus)

The `feat/contract-driven-self-healing` branch adds a contract-driven, multi-level repair pipeline under `plugins/sqlseed-ai/src/sqlseed_ai/`:

- `auto_heal/` — top-level orchestrator (`orchestrator.py`) + `time_budget.py` (deadline-aware iteration).
- `healer/` — multi-level repair: `level1_subgraph_healer`, `level2_column_healer`, `level3_compact_healer`. Supporting: `failure_classifier`, `oscillation`, `degrader` (semantic downgrade safety net), `post_repair`, `diff_learner`, `subgraph`, `context_detector`.
- `validator/` — constraint validation: `single_column`, `cross_column`, `composite_fk`, `shadow_fk_scan`, `dialect_parser`, `schema_snapshot`.
- `repair/` — `pipeline.py` + `strategies.py` + `executor.py` apply computed fixes to configs.
- `contracts/` — `registry.py`, `matrix.py`, `builtin_violations.py` define the violation→pattern contract matrix.
- `analyzer/` — LLM interaction: `_tool_calling`, `_streaming`, `_json_parser`, `_context`, `_caller`.

**Gotchas when editing this subsystem**:
- The `auto_heal.orchestrator` runs multiple convergence rounds; many `git log` entries are "Round N" fixes for specific cross-column CHECK patterns (Pattern 1/1b/4a/7a/19/24b/etc.). These are real constraint-handling rules, not throwaway — grep for the pattern number before removing.
- `degrader.py` is the "semantic downgrade safety net" — stripping generator/params when `derive_from` is present is intentional (see commit `78d15f9`).
- Self-referencing and composite FK resolution has many edge-case fixes (two-pass fill, `null_ratio=1.0` for empty-parent FK). See recent commits before changing `relation.py` / `_generation.py`.

## DOCS TO READ BEFORE SENSITIVE EDITS

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — authoritative architecture reference (4-package layout, plugin contracts, core-stability principle). Read before touching package boundaries or public API.
- **[CLAUDE.md](./CLAUDE.md)** — canonical "Never/Always" rules (the import-linter contracts encode these). Read before core changes.
- **`data_quality_demo/_regression_summary.md`** — current state of the self-healing regression scenarios (r1–r7) on this branch.

## COMMANDS

A `Makefile` wraps the common flows (`make help` lists all targets). Both forms work.

```bash
# Install core + plugins (dev mode)
pip install -e ".[dev,all]"
pip install -e "./plugins/sqlseed-cli"
pip install -e "./plugins/sqlseed-ai"
pip install -e "./plugins/mcp-server-sqlseed"

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
make mutmut-results                 # show survivors

# Docs
make docs-serve                     # mkdocs serve
make docs-build                     # mkdocs build --strict

# CLI (requires sqlseed-cli installed)
sqlseed fill app.db -t users -n 10000
sqlseed preview app.db -t users -n 5
sqlseed inspect app.db --show-mapping
```

## NOTES

- **Optional deps**: mimesis is optional. faker is a required core dependency. Base provider is type-routing only (no real data generation).
- **Plugin isolation**: sqlseed-cli, sqlseed-ai, mcp-server-sqlseed each have separate pyproject.toml, install separately. `mcp-server-sqlseed` installs as package `mcp-server-sqlseed` but its import module is **`mcp_server_sqlseed`** (hyphens → underscores); `server.py` exposes the FastMCP server, `__main__` is the entrypoint.
- **Core has no CLI**: `src/sqlseed/` has no `cli/` directory. Install `sqlseed-cli` to get the `sqlseed` command. Core has no `[project.scripts]`.
- **mypy strict**: Strict on `src/` and `plugins/` source code; test directories (`tests/`, `plugins/*/tests/`) excluded.
- **ruff config**: Line length 120, isort known-first-party=["sqlseed"], known-third-party=["sqlseed_ai", "sqlseed_cli"].
- **Test layout**: Core tests in `tests/`; plugin tests co-located with plugins (`plugins/*/tests/`). Plugin conftest re-exports root fixtures from `tests/conftest.py`.
- **`data_quality_demo/` and `scripts/` are scratch**: regression logs, generated `.db`/`.sql`/`.yaml` files, and ad-hoc harnesses. Useful as references for the self-healing scenarios but not shipped artifacts — don't rely on their contents being stable.
