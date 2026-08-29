<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-08-30 -->

# test_database

## Purpose

Database adapter layer tests. Covers dual-adapter functionality, PRAGMA optimization, dialect abstraction, and SQL safety. 10 files, 265 test functions.

## Key Files

| File | Tests | Description |
|------|------:|-------------|
| `conftest.py` | — | Local fixtures: `sa_adapter` (tmp_db-backed SQLAlchemyAdapter), `empty_sa_adapter` (empty tmp_path DB) |
| `test_dialect.py` | 92 | Dialect protocol, SQLiteDialect, PostgresDialect |
| `test_helpers.py` | 38 | fetch_index_info/sample_rows/batch_insert helpers |
| `test_sqlalchemy_adapter.py` | 27 | SQLAlchemyAdapter contract (default adapter) |
| `test_sqlite_schema.py` | 25 | `detect_sqlite_autoincrement` |
| `test_sqlalchemy_adapter_boundary.py` | 21 | boundary conditions |
| `test_adapter_contract.py` | 19 | adapter protocol contract |
| `test_raw_sqlite_adapter.py` | 13 | RawSQLiteAdapter (test-only adapter) |
| `test_sql_safe.py` | 12 | SQL injection vectors |
| `test_optimizer.py` | 10 | PragmaOptimizer + restore-on-exception |
| `test_sqlalchemy_adapter_url.py` | 8 | multi-DB URL connections |

## For AI Agents

### Working In This Directory

- Adapter tests require a real SQLite database, use the `tmp_db` fixture
- SQL safety tests must cover various injection attack vectors
- Optimizer tests must verify PRAGMA setting restoration logic (including restoration on exceptions)
- Dialect tests verify DB-specific behavior abstraction (type normalization, autoincrement detection, identifier quoting)

### Testing Requirements

```bash
pytest tests/test_database/
```

### Common Patterns

- Use the global `tmp_db` / `raw_adapter` fixtures from `conftest.py`
- Multi-DB URL tests use `--url` connection mode (PostgreSQL via testcontainers requires Docker)

## Dependencies

### Internal

- `src/sqlseed/database/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
