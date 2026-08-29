# SRC/SQLSEED PACKAGE

**Last updated:** 2026-08-30

## OVERVIEW

Main package. Public API in `__init__.py`. Core orchestration in `core/`. Data generation in `generators/`.

## STRUCTURE

```
src/sqlseed/
├── __init__.py       # Public API: fill, connect, fill_from_config, preview, load_config
├── _version.py       # Version info (importlib.metadata dynamic detection)
├── py.typed          # PEP 561 type marker
├── core/             # Orchestration engine: 17 top-level files + orchestrator/ package (6 files) = 23 files
├── generators/       # Data providers: base, faker, mimesis + dispatch, registry (9 files, 35 generator types)
├── database/         # Database adapters: SQLAlchemy (production), raw sqlite3 (testing) + dialect, optimizer, helpers (11 files)
├── plugins/          # Plugin system: hookspecs (12 hooks), manager (3 files)
├── config/           # Pydantic models (9 classes), YAML loader, snapshot manager (4 files)
└── _utils/           # Internal utilities: sql_safe, metrics, progress, logger, paths (6 files)
```

## FILE INVENTORY (per-module entry points)

| Module | Files | Key symbols (largest first) |
|--------|-------|------------------------------|
| `core/` | 23 | `relation.py` [1033L] RelationResolver+SharedPool, `mapper.py` [630L] ColumnMapper+GeneratorSpec, `stream.py` [675L] DataStream, `features.py` [468L] StructuralFeatureExtractor, `check_parser.py` [427L] CheckConstraintParser |
| `core/orchestrator/` | 6 | `_generation.py` [524L] GenerationMixin, `_specs.py` [502L] SpecResolverMixin, `_query.py` [251L] QueryMixin, `_connection.py` [243L] ConnectionMixin, `__init__.py` [57L] DataOrchestrator |
| `generators/` | 9 | `base_provider.py` [501L] BaseProvider, `faker_provider.py` [289L], `mimesis_provider.py` [247L], `_dispatch.py` [150L] GeneratorDispatchMixin, `registry.py` [162L] ProviderRegistry |
| `database/` | 11 | `sqlalchemy_adapter.py` [846L] SQLAlchemyAdapter+SQLAlchemyBatchInserter, `raw_sqlite_adapter.py` [337L], `_dialect.py` [228L] Dialect+SQLite/Postgres, `_protocol.py` [176L] DatabaseAdapter+4 info dataclasses |
| `plugins/` | 3 | `hookspecs.py` [177L] SqlseedHookSpec (12 hooks), `manager.py` [58L] PluginManager |
| `config/` | 4 | `models.py` [259L] 9 Pydantic classes, `loader.py` [184L] load/save/generate_template, `snapshot.py` [114L] SnapshotManager |
| `_utils/` | 6 | `progress.py` [423L] 3 progress backends, `paths.py` [105L], `sql_safe.py` [84L], `metrics.py` [81L], `logger.py` [67L] |

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
