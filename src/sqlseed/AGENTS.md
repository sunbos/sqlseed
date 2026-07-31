# SRC/SQLSEED PACKAGE

**Last updated:** 2026-07-12

## OVERVIEW

Main package. Public API in `__init__.py`. Core orchestration in `core/`. Data generation in `generators/`.

## STRUCTURE

```
src/sqlseed/
├── __init__.py       # Public API: fill, connect, fill_from_config, preview, load_config
├── _version.py       # Version info (importlib.metadata dynamic detection)
├── py.typed          # PEP 561 type marker
├── core/             # Orchestration engine: orchestrator, mapper, schema, constraints, DAG, enrichment, transform, stream (22 files)
├── generators/       # Data providers: base, faker, mimesis + dispatch, registry (9 files)
├── database/         # Database adapters: SQLAlchemy (production), raw sqlite3 (testing) + dialect, optimizer, helpers (11 files)
├── plugins/          # Plugin system: hookspecs (12 hooks), manager (3 files)
├── config/           # Pydantic models, YAML loader, snapshot manager (4 files)
└── _utils/           # Internal utilities: sql_safe, metrics, progress, logger, paths (6 files)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Public API | `__init__.py` | fill, connect, fill_from_config, preview, load_config |
| Orchestrator | `core/orchestrator/` | DataOrchestrator package (4 mixins + shared _common) |
| Column mapping | `core/mapper.py` | 9-level strategy chain |
| Schema inference | `core/schema.py` | SchemaInferrer class |
| Data stream | `core/stream.py` | DataStream + constraint backtracking |
| Base provider | `generators/base_provider.py` | 35 built-in generators, fallback provider with no external dependencies |
| DB adapters | `database/` | SQLAlchemyAdapter (required), RawSQLiteAdapter (test-only) |
| Plugin hooks | `plugins/hookspecs.py` | 12 pluggy hook definitions |
| Config models | `config/models.py` | Pydantic: GeneratorConfig, TableConfig, ColumnConfig, ColumnConstraintsConfig, ColumnAssociation |

## CONVENTIONS

- **Imports**: Always `from __future__ import annotations` first
- **Logging**: `logger = get_logger(__name__)` at module top
- **SQL safety**: `quote_identifier()` for all identifiers
- **Optional deps**: try/except for mimesis, psycopg (faker is required)
- **Provider protocol**: Implement `DataProvider` protocol, no base class required
- **Multi-DB support**: `db_path` (SQLite) and `url` (database URL) are mutually exclusive
- **Exception handling**: Use `sqlalchemy.exc.*` in SQLAlchemyAdapter; `sqlite3.*` only in RawSQLiteAdapter/PragmaOptimizer

## ANTI-PATTERNS

- **NEVER** import third-party libs without try/except (except faker, which is required)
- **NEVER** use raw SQL string formatting for identifiers
- **NEVER** use `assert` for runtime validation → use `RuntimeError`/`ValueError`
- **ALWAYS** use SQLAlchemyAdapter for multi-DB support
- **ALWAYS** use `from __future__ import annotations`
