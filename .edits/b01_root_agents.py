from _edit_helper import edit

ROOT = "/tmp/wt-multi-db"

# ---- Item 1: root AGENTS.md ----
edit(f"{ROOT}/AGENTS.md",
     "**Generated:** 2026-05-01\n**Commit:** f89f018\n**Branch:** main",
     "**Generated:** 2026-07-29\n**Commit:** 466d7b8\n**Branch:** feat/multi-db-support")

edit(f"{ROOT}/AGENTS.md",
     "│   ├── __init__.py       # Public API: fill, connect, fill_from_config, preview\n",
     "│   ├── __init__.py       # Public API: fill, connect, fill_from_config, preview, load_config\n")

edit(f"{ROOT}/AGENTS.md",
     "│   ├── database/         # DB adapters: SQLAlchemy (required, SQLite+PostgreSQL), raw sqlite3 (test-only)\n",
     "│   ├── database/         # DB adapters: sqlalchemy_adapter (required, SQLite+PostgreSQL), raw_sqlite_adapter (test-only) + _protocol, _base_adapter, _dialect (Dialect), _type_normalizer (TypeNormalizer), _bulk_optimizer (BulkWriteOptimizer), optimizer, _helpers, _sqlite_schema\n")

edit(f"{ROOT}/AGENTS.md",
     '- **ruff config**: Line length 120, isort known-first-party=["sqlseed"], known-third-party=["sqlseed_ai", "sqlseed_cli"].',
     '- **ruff config**: Line length 120, isort known-first-party=["sqlseed"], known-third-party=["sqlseed_ai", "sqlseed_cli", "mcp_server_sqlseed"].')
