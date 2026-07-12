<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-07-12 -->

# test_database

## Purpose

Database adapter layer tests. Covers dual-adapter functionality, PRAGMA optimization, dialect abstraction, and SQL safety.

## Key Files

| File | Description |
|------|-------------|
| `test_raw_sqlite_adapter.py` | RawSQLiteAdapter functional tests |
| `test_sqlalchemy_adapter.py` | SQLAlchemyAdapter contract tests (default adapter) |
| `test_sqlalchemy_adapter_boundary.py` | SQLAlchemyAdapter boundary condition tests |
| `test_sqlalchemy_adapter_url.py` | SQLAlchemyAdapter multi-DB URL connection tests |
| `test_adapter_contract.py` | Adapter protocol contract tests |
| `test_sqlite_schema.py` | SQLite AUTOINCREMENT detection tests (`detect_sqlite_autoincrement`) |
| `test_dialect.py` | Dialect protocol, SQLiteDialect, PostgresDialect contract tests |
| `test_optimizer.py` | PragmaOptimizer PRAGMA optimization tests |
| `test_helpers.py` | Database helper function tests |
| `test_sql_safe.py` | SQL injection protection tests |

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
