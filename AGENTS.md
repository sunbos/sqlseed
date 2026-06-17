# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-01
**Commit:** f89f018
**Branch:** main

## OVERVIEW

Declarative SQLite test data generation toolkit. YAML/JSON config or Python API. Auto-infers schema, 9-level column mapping, 31 generators, plugin system (pluggy). Gemma 4 Native Function Calling for AI-powered schema analysis.

**Stack**: Python 3.10+, hatchling build, ruff lint, mypy strict, pytest.

## STRUCTURE

```
sqlseed/
├── src/sqlseed/          # Main package
│   ├── __init__.py       # Public API: fill, connect, fill_from_config, preview
│   ├── core/             # Orchestrator, mapper, schema, constraints, DAG, enrichment, transform
│   ├── generators/       # Data providers: base, faker, mimesis
│   ├── database/         # SQLite adapters: raw, sqlite-utils + optimizer, helpers
│   ├── plugins/          # Plugin system: hookspecs, manager, mediator
│   ├── config/           # Pydantic models, YAML loader, snapshots
│   ├── cli/              # Click commands: main.py (fill, preview, inspect, init, replay) + ai_commands.py (ai-suggest)
│   └── _utils/           # Internal: sql_safe, metrics, progress, logger, schema_helpers
├── tests/                # pytest suite, conftest fixtures
├── plugins/
│   ├── sqlseed-ai/       # LLM-powered schema analysis
│   └── mcp-server-sqlseed/  # MCP server: schema inspect, AI YAML gen, fill
├── docs/                 # mkdocs-material site
└── examples/             # Usage examples
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new generator | `src/sqlseed/generators/` | Implement in base_provider.py or create new provider |
| Modify column mapping | `src/sqlseed/core/mapper.py` | 9-level strategy chain |
| Add CLI command | `src/sqlseed/cli/main.py` or `ai_commands.py` | Core commands in main.py; AI commands in ai_commands.py |
| Add plugin hook | `src/sqlseed/plugins/hookspecs.py` | pluggy hookspec |
| Modify schema inference | `src/sqlseed/core/schema.py` | SchemaInferrer class |
| Change batch insert | `src/sqlseed/database/` | Two adapters: raw, sqlite-utils |
| Add test fixture | `tests/conftest.py` | tmp_db, tmp_db_with_data, unique_test_db |
| Configure AI plugin | `plugins/sqlseed-ai/` | Separate pyproject.toml, Gemma 4 multi-backend (Google AI Studio, LM Studio, Ollama, OpenAI-compatible) |
| Add MCP tool | `plugins/mcp-server-sqlseed/` | FastMCP decorators, 3 Gemma 4 tools: gemma4_analyze, gemma4_agent_fill, list_gemma_models |

## CONVENTIONS

- **Type hints**: `from __future__ import annotations` at top of every file
- **Logging**: structlog via `sqlseed._utils.logger.get_logger(__name__)`
- **SQL safety**: Always use `quote_identifier()` from `_utils/sql_safe.py`
- **Test naming**: `test_<module>.py` mirrors `src/sqlseed/<module>/`
- **Provider pattern**: Implement `DataProvider` protocol (no base class required)
- **Entry points**: Register providers via `pyproject.toml` `[project.entry-points."sqlseed"]`

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER** use raw string formatting for SQL identifiers → use `quote_identifier()`
- **NEVER** import third-party libs without try/except in provider files (optional deps)
- **NEVER** suppress type errors with `as any` or `@ts-ignore`
- **NEVER** use `assert` for runtime validation → use `RuntimeError`/`ValueError` (asserts can be optimized away with `-O`)
- **ALWAYS** use `from __future__ import annotations` (enforced by ruff)
- **ALWAYS** handle `HAS_SQLITE_UTILS` flag in database layer

## UNIQUE STYLES

- **Provider fallback chain**: mimesis → faker → base (auto-degrades)
- **AI backend fallback chain**: Google AI Studio → LM Studio → Ollama (multi-backend)
- **Gemma 4 Native Function Calling**: `GEMMA_TOOLS` (analyze_schema) with auto-fallback to JSON mode
- **Context manager pattern**: `DataOrchestrator` is a context manager
- **Plugin mediation**: `PluginMediator` bridges plugins and core (not direct calls)
- **DAG-based column ordering**: `ColumnDAG` handles derive_from dependencies
- **SnapshotManager**: save/load/list_snapshots only; CLI `replay` uses load() + DataOrchestrator.from_config()

## COMMANDS

```bash
# Install
pip install -e ".[dev,all]"

# Test
pytest                              # All tests
pytest tests/test_core/             # Core only
pytest --cov=sqlseed                # With coverage

# Lint
ruff check .                        # Lint
ruff format .                       # Format
mypy src plugins                    # Type check

# CLI
sqlseed fill app.db -t users -n 10000
sqlseed preview app.db -t users -n 5
sqlseed inspect app.db --show-mapping
```

## NOTES

- **Optional deps**: faker, mimesis are optional. Base provider always available.
- **Plugin isolation**: sqlseed-ai has separate pyproject.toml, installs separately.
- **mypy strict**: Full strict mode on src/ and plugins/. Tests relaxed.
- **ruff config**: Line length 120, isort known-first-party=["sqlseed"].
