# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-01
**Commit:** f89f018
**Branch:** main

## OVERVIEW

Declarative Multi-Database test data generation toolkit. YAML/JSON config or Python API. Auto-infers schema, 9-level column mapping, 31 generators, plugin system (pluggy). Supports SQLite (default) and PostgreSQL via SQLAlchemy. MySQL removed (deferred until PostgreSQL fully validated). Gemma 4 as long-term LLM backend (protocol-based native function calling).

**Stack**: Python 3.10+, hatchling build, ruff lint, mypy strict, pytest.

**Architecture**: 4 independent packages — `sqlseed` (core, offline), `sqlseed-cli` (CLI plugin), `sqlseed-ai` (AI plugin), `mcp-server-sqlseed` (MCP plugin). See [ARCHITECTURE.md](./ARCHITECTURE.md) for authoritative reference.

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
│   ├── sqlseed-ai/       # AI plugin: LLM schema analysis, Gemma 4 protocol-based tool calling
│   └── mcp-server-sqlseed/  # MCP server: rule-driven YAML gen + execute_fill (no LLM)
├── docs/                 # mkdocs-material site
└── examples/             # Usage examples
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new generator | `src/sqlseed/generators/` | Create new provider; base_provider is type-routing only, real data from faker/mimesis |
| Modify column mapping | `src/sqlseed/core/mapper.py` | 9-level strategy chain |
| Add CLI command | `plugins/sqlseed-cli/src/sqlseed_cli/main.py` | Core commands (fill, preview, inspect, init, replay) |
| Add AI CLI command | `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` | AI commands (ai-suggest), injected via entry_points |
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
- **ALWAYS** use `from __future__ import annotations` (enforced by ruff)
- **ALWAYS** use SQLAlchemyAdapter for multi-DB support; RawSQLiteAdapter for zero-dep tests

## UNIQUE STYLES

- **Provider fallback chain**: mimesis (optional, high-performance) → faker (required, standard) → base (type-routing only, no real data)
- **AI backend fallback chain**: Google AI Studio → LM Studio → Ollama (multi-backend)
- **Gemma 4 protocol-based tool calling**: `AIConfig.tool_calling_protocol: Literal["gemma4", "openai", "none"]` (Phase E). `GEMMA_TOOLS` shared across protocols; `resolve_tool_calling_protocol()` narrows based on backend support. Gemma4 is a long-term LLM backend (NOT competition-only).
- **Context manager pattern**: `DataOrchestrator` is a context manager
- **Plugin mediation**: `PluginMediator` bridges plugins and core (generic methods only: `apply_batch_transforms`, `apply_template_pool`). AI-specific `apply_ai_suggestions` moved to `sqlseed-ai` (Phase C), invoked via pluggy hook.
- **DAG-based column ordering**: `ColumnDAG` handles derive_from dependencies
- **SnapshotManager**: save/load/list_snapshots only; CLI `replay` uses load() + DataOrchestrator.from_config()

## COMMANDS

```bash
# Install core + plugins (dev mode)
pip install -e ".[dev,all]"
pip install -e "./plugins/sqlseed-cli"
pip install -e "./plugins/sqlseed-ai"
pip install -e "./plugins/mcp-server-sqlseed"

# Test
pytest                              # All tests (core + plugins)
pytest tests/test_core/             # Core only
pytest plugins/sqlseed-ai/tests/    # AI plugin only
pytest --cov=sqlseed                # With coverage

# Lint
ruff check src/ tests/ plugins/     # Lint
ruff format src/ tests/ plugins/    # Format
mypy                                 # Type check (uses pyproject.toml config)

# CLI (requires sqlseed-cli installed)
sqlseed fill app.db -t users -n 10000
sqlseed preview app.db -t users -n 5
sqlseed inspect app.db --show-mapping
```

## NOTES

- **Optional deps**: mimesis is optional. faker is a required core dependency. Base provider is type-routing only (no real data generation).
- **Plugin isolation**: sqlseed-cli, sqlseed-ai, mcp-server-sqlseed each have separate pyproject.toml, install separately.
- **Core has no CLI**: `src/sqlseed/` has no `cli/` directory. Install `sqlseed-cli` to get the `sqlseed` command. Core has no `[project.scripts]`.
- **mypy strict**: Strict on `src/` and `plugins/` source code; test directories (`tests/`, `plugins/*/tests/`) excluded.
- **ruff config**: Line length 120, isort known-first-party=["sqlseed"], known-third-party=["sqlseed_ai", "sqlseed_cli"].
- **Test layout**: Core tests in `tests/`; plugin tests co-located with plugins (`plugins/*/tests/`). Plugin conftest re-exports root fixtures.
