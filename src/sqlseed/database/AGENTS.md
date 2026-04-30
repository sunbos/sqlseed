# DATABASE ADAPTER LAYER

## OVERVIEW

SQLite adapters: raw sqlite3 and sqlite-utils. Protocol-based design with pragma optimization.

## STRUCTURE

```
database/
├── _protocol.py          # DatabaseAdapter protocol, ColumnInfo, ForeignKeyInfo, IndexInfo
├── _base_adapter.py      # BaseSQLiteAdapter — shared logic (context manager, pragmas)
├── _helpers.py           # fetch_index_info, fetch_sample_rows, pragma helpers
├── _compat.py            # sqlite-utils compatibility shims
├── raw_sqlite_adapter.py # RawSQLiteAdapter — direct sqlite3 (8 files)
├── sqlite_utils_adapter.py # SQLiteUtilsAdapter — sqlite-utils wrapper
└── optimizer.py          # PragmaOptimizer, PragmaProfile — bulk write tuning
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add adapter method | `_protocol.py` | Add to DatabaseAdapter protocol |
| Implement adapter | New file | Extend BaseSQLiteAdapter |
| Modify pragma tuning | `optimizer.py` | PragmaProfile presets |
| Add helper function | `_helpers.py` | Shared SQL utilities |

## CONVENTIONS

- **Protocol**: Implement `DatabaseAdapter` (runtime_checkable)
- **Base class**: Extend `BaseSQLiteAdapter` for shared logic
- **Context manager**: All adapters use `__enter__`/`__exit__`
- **SQL safety**: Always `quote_identifier()`, `validate_table_name()`
- **Pragmas**: Use `PragmaOptimizer` for bulk write optimization

## ANTI-PATTERNS

- **NEVER** use raw string formatting for SQL identifiers
- **NEVER** skip `validate_table_name()` before table operations
- **ALWAYS** handle `HAS_SQLITE_UTILS` flag (optional dependency)
- **ALWAYS** use `apply_pragma_optimize()`/`apply_pragma_restore()` for bulk ops
