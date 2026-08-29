# DATABASE ADAPTER LAYER

**Last updated:** 2026-08-30

## OVERVIEW

DB adapters: SQLAlchemy (required core dependency, multi-DB) and raw sqlite3 (test-only fallback). Protocol-based design with dialect abstraction and pragma optimization. 11 files.

## FILE INVENTORY (file → lines → symbols)

| File | Lines | Symbols |
|------|------:|---------|
| `sqlalchemy_adapter.py` | 846 | `SQLAlchemyAdapter`, `SQLAlchemyBatchInserter` (production, multi-DB) |
| `raw_sqlite_adapter.py` | 337 | `RawSQLiteAdapter` (test-only) |
| `_base_adapter.py` | 207 | `BaseRawSQLiteAdapter` — shared native sqlite3 logic |
| `_dialect.py` | 228 | `Dialect`, `SQLiteDialect`, `PostgresDialect` |
| `_type_normalizer.py` | 157 | `NormalizedType`, `TypeNormalizer` |
| `optimizer.py` | 156 | `PragmaProfile`, `PragmaOptimizer` (SQLite PRAGMA tuning) |
| `_protocol.py` | 176 | `ColumnInfo`, `ForeignKeyInfo`, `IndexInfo`, `CheckConstraintInfo`, `DatabaseAdapter` protocol |
| `_helpers.py` | 145 | `fetch_index_info()`, `fetch_sample_rows()`, `batch_insert_rows()`, `apply_bulk_optimize/restore()` |
| `_sqlite_schema.py` | 105 | `_split_sql_definitions()`, `detect_sqlite_autoincrement()` |
| `_bulk_optimizer.py` | 182 | `BulkWriteOptimizer`, `SQLiteBulkOptimizer`, `PostgresBulkOptimizer` |
| `__init__.py` | 44 | exports |

## STRUCTURE

```
database/
├── __init__.py            # Public API exports
├── _protocol.py           # DatabaseAdapter protocol, ColumnInfo, ForeignKeyInfo, IndexInfo, CheckConstraintInfo
├── _base_adapter.py       # BaseRawSQLiteAdapter — shared native sqlite3 logic (context manager, PRAGMA)
├── _helpers.py            # fetch_index_info, fetch_sample_rows, batch_insert_rows, apply_bulk_optimize/restore
├── _bulk_optimizer.py     # BulkWriteOptimizer protocol, SQLiteBulkOptimizer, PostgresBulkOptimizer
├── _dialect.py            # Dialect protocol, SQLiteDialect, PostgresDialect
├── _sqlite_schema.py      # SQLite-specific schema introspection (AUTOINCREMENT detection via sqlite_master)
├── _type_normalizer.py    # TypeNormalizer — database type normalization
├── optimizer.py           # PragmaOptimizer, PragmaProfile — SQLite PRAGMA tuning
├── raw_sqlite_adapter.py  # RawSQLiteAdapter — direct sqlite3 (test-only)
└── sqlalchemy_adapter.py  # SQLAlchemyAdapter — unified multi-DB adapter (production)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add adapter method | `_protocol.py` | Add to DatabaseAdapter protocol |
| Implement adapter | New file | Extend BaseRawSQLiteAdapter or implement standalone |
| Modify pragma tuning | `optimizer.py` | PragmaProfile presets, PragmaOptimizer |
| Add helper function | `_helpers.py` | Shared SQL utilities |
| Add new dialect | `_dialect.py` | Implement Dialect protocol |
| SQLite schema introspection | `_sqlite_schema.py` | `detect_sqlite_autoincrement` parses CREATE TABLE from sqlite_master |
| Add bulk optimizer | `_bulk_optimizer.py` | Implement BulkWriteOptimizer protocol |
| Normalize types | `_type_normalizer.py` | TypeNormalizer for DB type mapping |
| Multi-DB support | `sqlalchemy_adapter.py` | SQLAlchemyAdapter with dialect detection |

## CONVENTIONS

- **Protocol**: Implement `DatabaseAdapter` (runtime_checkable)
- **Base class**: Extend `BaseRawSQLiteAdapter` for raw sqlite3 shared logic
- **Context manager**: All adapters use `__enter__`/`__exit__`
- **SQL safety**: Always `quote_identifier()`, `validate_table_name()`
- **Bulk optimization**: Use `apply_bulk_optimize()`/`apply_bulk_restore()` for bulk ops
- **Dialect abstraction**: Use `Dialect` protocol for DB-specific behavior (type normalization, autoincrement detection, identifier quoting)
- **BulkWriteOptimizer**: Abstract bulk write optimization (SQLite: PRAGMA, PG: SET synchronous_commit)
- **TypeNormalizer**: Normalize DB native types to sqlseed internal types (protects mapper.py rules)
- **Exception handling**: `PragmaOptimizer` only for SQLite, `sqlite3.DatabaseError` catch is correct; production uses `SQLAlchemyAdapter` with `sqlalchemy.exc.*` exceptions

## ANTI-PATTERNS

- **NEVER** use raw string formatting for SQL identifiers
- **NEVER** skip `validate_table_name()` before table operations
- **NEVER** use `BaseRawSQLiteAdapter` for production — use `SQLAlchemyAdapter`
- **ALWAYS** use `SQLAlchemyAdapter` for production; `RawSQLiteAdapter` for test-only
- **ALWAYS** use `apply_bulk_optimize()`/`apply_bulk_restore()` for bulk ops
- **NEVER** catch `sqlite3.*` exceptions in SQLAlchemyAdapter — use `sqlalchemy.exc.*`
