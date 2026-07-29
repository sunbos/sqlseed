# SRC/SQLSEED PACKAGE

## OVERVIEW

Main package. Public API in `__init__.py`. Core orchestration in `core/`. Data generation in `generators/`.

## STRUCTURE

```
src/sqlseed/
├── __init__.py       # Public API: fill, connect, fill_from_config, preview, load_config
├── _version.py       # __version__
├── py.typed          # PEP 561 typed marker
├── core/             # Orchestrator, mapper, schema, constraints, DAG, enrichment, transform (13 files)
├── generators/       # Data providers: base, faker, mimesis (10 files)
├── database/         # SQLite adapters: raw, sqlite-utils + optimizer, helpers (8 files)
├── plugins/          # Plugin system: hookspecs, manager (3 files)
├── config/           # Pydantic models, YAML loader, snapshots (4 files)
├── cli/              # Click commands: main.py (fill, preview, inspect, init, replay) + ai_commands.py (ai-suggest)
└── _utils/           # Internal: sql_safe, metrics, progress, logger, schema_helpers, paths (7 files)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Public API | `__init__.py` | fill, connect, fill_from_config, preview, load_config |
| Orchestrator | `core/orchestrator.py` | DataOrchestrator main engine |
| Column mapping | `core/mapper.py` | 9-level strategy chain |
| Schema inference | `core/schema.py` | SchemaInferrer class |
| Data stream | `generators/stream.py` | DataStream + constraint backtracking |
| Base provider | `generators/base_provider.py` | 31 generators, no deps |
| DB adapters | `database/` | RawSQLiteAdapter, SQLiteUtilsAdapter |
| Plugin hooks | `plugins/hookspecs.py` | 11 pluggy hook definitions |
| Config models | `config/models.py` | Pydantic: GeneratorConfig, TableConfig, ColumnConfig, ColumnConstraintsConfig, ColumnAssociation |

## CONVENTIONS

- **Imports**: Always `from __future__ import annotations` first
- **Logging**: `logger = get_logger(__name__)` at module top
- **SQL safety**: `quote_identifier()` for all identifiers
- **Optional deps**: try/except with `HAS_*` flags (e.g., `HAS_SQLITE_UTILS`)
- **Provider protocol**: Implement `DataProvider` protocol, no base class required

## ANTI-PATTERNS

- **NEVER** import third-party libs without try/except
- **NEVER** use raw SQL string formatting for identifiers
- **NEVER** use `assert` for runtime validation → use `RuntimeError`/`ValueError`
- **ALWAYS** handle `HAS_SQLITE_UTILS` in database layer
- **ALWAYS** use `from __future__ import annotations`
