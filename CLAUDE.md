# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is sqlseed

Python 3.10+ declarative SQLite test data generation toolkit. Single API call infers schema, picks generators via 9-level column mapping, streams data in batches, and maintains FK integrity across tables. Optional AI plugin (`sqlseed-ai`) adds LLM-powered schema analysis.

**Stack**: hatchling + hatch-vcs build, ruff lint, mypy strict, pytest. License: AGPL-3.0-or-later.

## Quick Start Commands

```bash
# Install in dev mode (all optional deps)
pip install -e ".[dev,all]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_orchestrator.py -v

# Run tests matching a pattern
pytest -k "test_fill" -v

# Run with coverage for a specific module
pytest --cov=sqlseed.core.orchestrator --cov-report=term-missing

# Lint and auto-fix
ruff check --fix src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/sqlseed/

# CLI usage
sqlseed fill app.db -t users -n 10000
sqlseed preview app.db -t users -n 5
```

## Architecture

Layered design with strict dependency direction (`→` means "depends on"):

```
cli/ → core/ → generators/
               database/
               plugins/
               config/

_utils/ → (no internal deps, used by all layers)
```

**Never**: `generators` → `core`, `database` → `core`, `_utils` → any upper layer.

### Key Modules

- **`core/orchestrator.py`** — `DataOrchestrator` is the central coordinator. Uses `CoreCtx` (db, schema, mapper, relation, shared_pool) and `ExtCtx` (registry, plugins, mediator, enrichment, metrics) dataclasses. `fill_table()` is the main entry point; `fill()` is its alias.
- **`core/mapper.py`** — `ColumnMapper` with 9-level strategy chain (autoincrement PK → user config → exact match → default check → pattern match → nullable → type fallback). 68 exact rules, 25 regex patterns.
- **`core/schema.py`** — `SchemaInferrer` reads SQLite schema + `CREATE TABLE` SQL for autoincrement detection.
- **`core/relation.py`** — `RelationResolver` + `SharedPool` for cross-table FK integrity. Implicit associations via name matching, explicit via `ColumnAssociation` config.
- **`core/column_dag.py`** — Topological sort for `derive_from` column dependencies.
- **`core/expression.py`** — `ExpressionEngine` using `simpleeval`. Timeout via thread (5s default). `ExpressionTimeoutError` on timeout. 21 whitelisted functions in `SAFE_FUNCTIONS`.
- **`core/constraints.py`** — `ConstraintSolver` for UNIQUE enforcement with backtracking. Supports probabilistic mode (SHA256 hash-based) for >100K rows.
- **`generators/`** — `DataProvider` protocol: `name`, `set_locale`, `set_seed`, `generate(type_name, **params)`. 24 generator types dispatched via `GeneratorDispatchMixin._GENERATOR_MAP`. Three providers: `BaseProvider` (always available), `FakerProvider`, `MimesisProvider`.
- **`database/`** — `DatabaseAdapter` protocol with two implementations: `SQLiteUtilsAdapter` (default, requires `sqlite-utils`) and `RawSQLiteAdapter` (fallback). `_compat.py` controls `HAS_SQLITE_UTILS` flag.
- **`plugins/`** — 11 pluggy hooks. `PluginManager` + `PluginMediator` bridge plugins and core.
- **`config/`** — Pydantic models (`GeneratorConfig`, `TableConfig`, `ColumnConfig`, `ColumnAssociation`), YAML/JSON loader, `SnapshotManager`.
- **`cli/main.py`** — Click commands: `fill`, `preview`, `inspect`, `ai-suggest`, `config-generate`. CLI log level via `SQLSEED_LOG_LEVEL` env var (default `WARNING`).

### Public API (`src/sqlseed/__init__.py`)

| Function | Purpose |
|----------|---------|
| `fill(db_path, *, table, count, ...)` | Single table zero-config fill |
| `connect(db_path, *, ...)` | Returns `DataOrchestrator` context manager |
| `preview(db_path, *, table, count, ...)` | Preview data without writing |
| `fill_from_config(config_path)` | Batch fill from YAML/JSON config |
| `load_config(path)` | Load config as `GeneratorConfig` |

### Config Model Hierarchy

`GeneratorConfig` → `list[TableConfig]` → `list[ColumnConfig]` + `list[ColumnAssociation]`

ColumnConfig supports two mutually exclusive modes (enforced by Pydantic `model_validator`):
- **Source mode**: `generator` + `params` + `null_ratio` + `provider`
- **Derived mode**: `derive_from` + `expression`

### Plugin Hooks (11 total)

| Hook | firstresult | When |
|------|:-----------:|------|
| `sqlseed_register_providers(registry)` | ✗ | `_ensure_connected()` |
| `sqlseed_register_column_mappers(mapper)` | ✗ | `_ensure_connected()` |
| `sqlseed_ai_analyze_table(...)` | ✓ | `apply_ai_suggestions()` |
| `sqlseed_before_generate(table_name, count, config)` | ✗ | Before main generation loop |
| `sqlseed_after_generate(table_name, count, elapsed)` | ✗ | After generation completes |
| `sqlseed_transform_row(table_name, row)` | ✗ | Per-row (hot path) |
| `sqlseed_transform_batch(table_name, batch)` | ✗ | `apply_batch_transforms()` |
| `sqlseed_before_insert(table_name, batch_number, batch_size)` | ✗ | Before each batch write |
| `sqlseed_after_insert(table_name, batch_number, rows_inserted)` | ✗ | After each batch write |
| `sqlseed_shared_pool_loaded(table_name, shared_pool)` | ✗ | After `register_shared_pool()` |
| `sqlseed_pre_generate_templates(...)` | ✓ | `apply_template_pool()` |

## Coding Conventions

- Every `.py` file starts with `from __future__ import annotations`
- All public functions use keyword-only arguments (except `generate_choice(choices)`)
- SQL identifiers: always use `quote_identifier()` from `_utils/sql_safe.py`
- Logging: `structlog` via `sqlseed._utils.logger.get_logger(__name__)`
- New config models: Pydantic `BaseModel`
- New providers/adapters: must satisfy existing `Protocol` definitions
- Optional deps (faker, mimesis, sqlite-utils): always lazy import with try/except
- Register new providers via `pyproject.toml` `[project.entry-points."sqlseed"]`

### Import Style

```python
# Type-only imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo

# Optional deps: lazy import inside methods
def method(self):
    import sqlite_utils  # not at module top
```

## Testing

- Fixtures in `tests/conftest.py`: `tmp_db` (users + orders tables), `tmp_db_with_data`, `bank_cards_db`, `create_card_info_db()`
- Use real SQLite via `tmp_path` fixture, never mock the database layer
- CLI tests: use `click.testing.CliRunner`, never subprocess
- AI plugin tests: `pytest.importorskip("sqlseed_ai")`
- Benchmarks: `tests/benchmarks/` with `pytest-benchmark`

## Critical Pitfalls

1. **Seed handling**: Don't set provider seed in orchestrator — `DataStream.__init__` does it (`set_seed` only when `seed is not None`)
2. **Hook return values**: pluggy returns `list[result]` for non-firstresult hooks, not a single value
3. **sqlite-utils API**: `table.columns_dict` returns `{name: Python_type_class}`, not strings
4. **Mimesis locale**: Use short codes (`"en"`, `"zh"`) not Faker-style (`"en_US"`, `"zh_CN"`)
5. **Memory**: Never collect all rows before writing — use `DataStream.generate()` iterator
6. **Expression timeout**: Always handle `ExpressionTimeoutError`; timeout threads can't be killed
7. **Batch transforms chain**: Last non-`None` result wins — it's not accumulative
8. **PRAGMA restore**: Must be in `finally` block or DB stays in unsafe state
9. **sqlite-utils optional**: `database/_compat.py` controls `HAS_SQLITE_UTILS`; never `import sqlite_utils` in core paths
10. **Provider fallback**: `_ensure_connected()` silently falls back to `"base"` on provider load failure

## Plugins (separate packages)

- `plugins/sqlseed-ai/` — LLM-powered schema analysis via OpenRouter. Has its own `pyproject.toml`. Install: `pip install -e "./plugins/sqlseed-ai"`
- `plugins/mcp-server-sqlseed/` — MCP server for schema inspect, AI YAML gen, fill. Install: `pip install -e "./plugins/mcp-server-sqlseed"`

## Dependencies

**Core**: sqlite-utils, pydantic, pluggy, structlog, pyyaml, click, rich, typing_extensions, simpleeval, rstr
**Optional**: faker (`sqlseed[faker]`), mimesis (`sqlseed[mimesis]`)
**Dev**: pytest, pytest-cov, pytest-asyncio, pytest-benchmark, ruff, mypy, pre-commit
