# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-01
**Commit:** cb63210
**Branch:** main

## OVERVIEW

Declarative SQLite test data generation toolkit. YAML/JSON config or Python API. Auto-infers schema, 7-level column mapping, 31 generators, plugin system (pluggy).

**Stack**: Python 3.10+, hatchling build, ruff lint, mypy strict, pytest.

## STRUCTURE

```
sqlseed/
├── src/sqlseed/          # Main package
│   ├── __init__.py       # Public API: fill, connect, fill_from_config, preview
│   ├── core/             # Orchestrator, mapper, schema, constraints, DAG
│   ├── generators/       # Data providers: base, faker, mimesis
│   ├── database/         # SQLite adapters: raw, sqlite-utils
│   ├── plugins/          # Plugin system: hookspecs, manager
│   ├── config/           # Pydantic models, YAML loader, snapshots
│   ├── cli/              # Click commands: fill, preview, inspect, ai-suggest
│   └── _utils/           # Internal: sql_safe, metrics, progress, logger
├── tests/                # pytest suite, conftest fixtures
├── plugins/
│   ├── sqlseed-ai/       # LLM-powered schema analysis
│   └── mcp-server-sqlseed/  # MCP server for AI assistants
├── docs/                 # mkdocs-material site
└── examples/             # Usage examples
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new generator | `src/sqlseed/generators/` | Implement in base_provider.py or create new provider |
| Modify column mapping | `src/sqlseed/core/mapper.py` | 7-level strategy chain |
| Add CLI command | `src/sqlseed/cli/main.py` | Click decorators |
| Add plugin hook | `src/sqlseed/plugins/hookspecs.py` | pluggy hookspec |
| Modify schema inference | `src/sqlseed/core/schema.py` | SchemaInferrer class |
| Change batch insert | `src/sqlseed/database/` | Two adapters: raw, sqlite-utils |
| Add test fixture | `tests/conftest.py` | tmp_db, tmp_db_with_data, bank_cards_db |
| Configure AI plugin | `plugins/sqlseed-ai/` | Separate pyproject.toml |

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
- **ALWAYS** use `from __future__ import annotations` (enforced by ruff)
- **ALWAYS** handle `HAS_SQLITE_UTILS` flag in database layer

## UNIQUE STYLES

- **Provider fallback chain**: mimesis → faker → base (auto-degrades)
- **Context manager pattern**: `DataOrchestrator` is a context manager
- **Plugin mediation**: `PluginMediator` bridges plugins and core (not direct calls)
- **DAG-based column ordering**: `ColumnDAG` handles derive_from dependencies

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
