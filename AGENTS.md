# AGENTS.md — AI Agent Instructions for sqlseed

This file provides context and instructions for AI coding agents working on the sqlseed codebase.

## Project Overview

**sqlseed** is a declarative SQLite test data generation toolkit. It orchestrates mature libraries (`sqlite-utils`, `Faker`, `Mimesis`, `Pydantic`, `pluggy`) to provide zero-config, declarative, and CLI-based data generation for SQLite databases.

## Architecture

```
src/sqlseed/
├── core/           → Orchestration layer
│   ├── orchestrator.py     → Central engine
│   ├── mapper.py           → Column name → generator strategy (8-level chain)
│   ├── column_dag.py       → [v2.0] Column dependency DAG + topological sort
│   ├── expression.py       → [v2.0] Safe expression engine (simpleeval-based)
│   ├── constraints.py      → [v2.0] Uniqueness/range constraint solver with backtracking
│   ├── transform.py        → [v2.0] User Python script dynamic loader
│   ├── schema.py           → Schema inference from DB
│   ├── relation.py         → Foreign key resolution + topological sort
│   └── result.py           → GenerationResult dataclass
├── generators/     → Data generation (protocol, registry, base/faker/mimesis providers, stream)
├── database/       → Database access (protocol, sqlite-utils + raw adapters, PRAGMA optimizer)
├── plugins/        → Plugin system (pluggy hookspecs + manager)
├── config/         → Configuration (Pydantic models with ColumnConstraints/derive_from/transform)
├── cli/            → CLI interface (click commands, --transform, ai-suggest)
└── _utils/         → Internal utilities (sql_safe, schema_helpers, metrics, progress, logger)
```

## Key Design Decisions

1. **Protocol-based interfaces**: `DatabaseAdapter` and `DataProvider` are Python Protocols (structural typing). Adapters must satisfy these interfaces without inheriting from them.

2. **Plugin system**: Based on `pluggy`. Hooks are defined in `plugins/hookspecs.py`. Plugins are discovered via `pyproject.toml` entry-points in the `"sqlseed"` group.

3. **Streaming architecture**: `DataStream` generates data in batches via `Iterator[list[dict]]`, preventing OOM for large datasets.

4. **Multi-level column mapping**: `ColumnMapper` uses an 8-level strategy chain:
   - User config > Custom exact > Built-in exact > Custom pattern > Built-in pattern > Skip (DEFAULT/NULL) > Type-faithful fallback > Default
   - **Type-faithful fallback**: `VARCHAR(32)` → string max 32 chars; `INT8` → 0~255; `BLOB(1024)` → 1024 bytes

5. **Column Dependency DAG** (v2.0): Columns can declare dependencies via `derive_from` + `expression`. Generation order is determined by topological sort. Derived columns (e.g., `last_eight = card_number[-8:]`) are computed after their source columns.

6. **Expression Engine** (v2.0): Safe expression evaluator based on `simpleeval`. Supports string slicing (`value[-8:]`), function calls (`upper(value)`), and math. No `import`/`exec`/file I/O allowed.

7. **Constraint Solver** (v2.0): Handles uniqueness constraints with retry and backtracking. When a derived column's unique constraint fails, the solver backtracks to regenerate the source column.

8. **Transform Scripts** (v2.0): Users can write Python scripts with a `transform_row(row, ctx)` function. Loaded dynamically via `importlib`. This is the escape hatch for extreme business logic.

9. **PRAGMA optimization**: Three tiers based on row count — LIGHT (<10K), MODERATE (10K-100K), AGGRESSIVE (>100K).

10. **AI as first-class plugin**: The `sqlseed-ai` package is a separate pip-installable plugin that integrates via hooks. AI role is **advisor** (analyzes schema → outputs YAML suggestions → human reviews).

## Code Conventions

- **Python 3.10+** — Use `X | Y` union syntax, not `Union[X, Y]`
- **`from __future__ import annotations`** — Required in every module
- **Type annotations** — All functions must have complete type annotations
- **`ClassVar`** — Use for class-level constants in dataclasses/classes
- **Structured logging** — Use `structlog` via `sqlseed._utils.logger.get_logger(__name__)`
- **SQL safety** — Always use `quote_identifier()` from `_utils/sql_safe.py` for table/column names
- **No f-string SQL** — Never use f-strings with user-provided values in SQL queries
- **Tests** — Every module has corresponding tests in `tests/`. Target ≥85% coverage.

## Building & Testing

```bash
# Install in development mode
pip install -e ".[dev,all]"

# Run tests
pytest

# Lint
ruff check src/ tests/

# Type check
mypy src/sqlseed/
```

## Common Tasks

### Adding a new Generator

1. Create `src/sqlseed/generators/new_provider.py`
2. Implement all methods from `DataProvider` Protocol (`generators/_protocol.py`)
3. Register via `ProviderRegistry.register()` or entry-points
4. Add tests in `tests/test_generators/test_new_provider.py`

### Adding a new Hook

1. Add hook spec in `src/sqlseed/plugins/hookspecs.py`
2. Call the hook at appropriate point in `orchestrator.py`
3. Add tests in `tests/test_plugins/test_hookspecs.py`

### Adding a new CLI Command

1. Add command function in `src/sqlseed/cli/main.py` with `@cli.command()` decorator
2. Add tests using `click.testing.CliRunner` in `tests/test_cli.py`

## Important Files

| File | Purpose |
|------|---------|
| `implementation_plan.md` | Architecture design document v2.0 (source of truth) |
| `pyproject.toml` | Project configuration, dependencies, entry-points |
| `src/sqlseed/__init__.py` | Public API surface (`fill`, `connect`, `preview`, `fill_from_config`) |
| `src/sqlseed/core/orchestrator.py` | Central orchestration engine |
| `src/sqlseed/core/mapper.py` | Column name → generator strategy mapping (8-level chain) |
| `src/sqlseed/core/column_dag.py` | [v2.0] Column dependency DAG + topological sort |
| `src/sqlseed/core/expression.py` | [v2.0] Safe expression engine (simpleeval) |
| `src/sqlseed/core/constraints.py` | [v2.0] Constraint solver (unique, backtrack) |
| `src/sqlseed/core/transform.py` | [v2.0] User transform script loader |
| `src/sqlseed/generators/_protocol.py` | DataProvider interface contract |
| `src/sqlseed/database/_protocol.py` | DatabaseAdapter interface contract |
| `src/sqlseed/plugins/hookspecs.py` | All plugin hook definitions |

## Do NOT

- Do not add direct dependencies on `faker` or `mimesis` to the core package — they are optional
- Do not use `import random` directly — use provider's `_rng` instance for reproducibility
- Do not bypass the `quote_identifier()` utility for SQL identifiers
- Do not add `firstresult=True` to transform hooks — they must support chain-style processing
- Do not create circular imports between layers (core → generators → database is the dependency direction)
