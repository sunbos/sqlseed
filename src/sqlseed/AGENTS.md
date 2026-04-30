# SRC/SQLSEED PACKAGE

## OVERVIEW

Main package. Public API in `__init__.py`. Core orchestration in `core/`. Data generation in `generators/`.

## STRUCTURE

```
src/sqlseed/
├── __init__.py       # Public API: fill, connect, fill_from_config, preview
├── core/             # Orchestrator, mapper, schema, constraints, DAG (13 files)
├── generators/       # Data providers: base, faker, mimesis (10 files)
├── database/         # SQLite adapters: raw, sqlite-utils (8 files)
├── plugins/          # Plugin system: hookspecs, manager (3 files)
├── config/           # Pydantic models, YAML loader, snapshots (4 files)
├── cli/              # Click commands: fill, preview, inspect, ai-suggest (2 files)
└── _utils/           # Internal: sql_safe, metrics, progress, logger (6 files)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Public API | `__init__.py` | fill, connect, fill_from_config, preview |
| Orchestrator | `core/orchestrator.py` | DataOrchestrator main engine (557 lines) |
| Column mapping | `core/mapper.py` | 7-level strategy chain |
| Schema inference | `core/schema.py` | SchemaInferrer class |
| Data stream | `generators/stream.py` | DataStream + constraint backtracking |
| Base provider | `generators/base_provider.py` | 31 generators, no deps (677 lines) |
| DB adapters | `database/` | RawSQLiteAdapter, SQLiteUtilsAdapter |
| Plugin hooks | `plugins/hookspecs.py` | 11 pluggy hook definitions |
| Config models | `config/models.py` | Pydantic: GeneratorConfig, TableConfig, ColumnConfig |

## CONVENTIONS

- **Imports**: Always `from __future__ import annotations` first
- **Logging**: `logger = get_logger(__name__)` at module top
- **SQL safety**: `quote_identifier()` for all identifiers
- **Optional deps**: try/except with `HAS_*` flags (e.g., `HAS_SQLITE_UTILS`)
- **Provider protocol**: Implement `DataProvider` protocol, no base class required

## ANTI-PATTERNS

- **NEVER** import third-party libs without try/except
- **NEVER** use raw SQL string formatting for identifiers
- **ALWAYS** handle `HAS_SQLITE_UTILS` in database layer
- **ALWAYS** use `from __future__ import annotations`
