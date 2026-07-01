# sqlseed

**Declarative Multi-Database test data generation toolkit.**

Generate realistic test data for SQLite and PostgreSQL databases using YAML/JSON config or Python API.
Auto-infers schema, 9-level column mapping, 34 generators, plugin system (pluggy).

## Quick Start

```bash
pip install sqlseed[mimesis]
```

```python
from sqlseed import fill

# SQLite (default)
fill("app.db", tables={"users": {"count": 100}})

# PostgreSQL (requires: pip install "sqlseed[postgres]")
fill(
    "postgresql+psycopg://user:password@localhost:5432/mydb",
    tables={"users": {"count": 100}},
)
```

The same API works across SQLite and PostgreSQL — schema inference, FK resolution, expression engine, and plugin hooks all run identically.

## CLI

```bash
sqlseed fill app.db -t users -n 10000
sqlseed preview app.db -t users -n 5
sqlseed inspect app.db --show-mapping
```

## Features

- **9-level column mapping strategy** — auto-infers generators from column names
- **32 built-in generators** — names, emails, phones, dates, UUIDs, and more
- **Plugin system** — extend via pluggy hooks
- **Expression engine** — derive columns from other columns (`{{ email.split('@')[1] }}`)
- **AI-powered schema analysis** — Gemma 4 Native Function Calling (optional)

## Documentation

- [Architecture](architecture.md) — internal design, 9-level mapper, DAG ordering
- [Gemma 4 Integration](gemma4-integration.md) — AI schema analysis setup

## Installation Variants

| Command | Description |
|---------|-------------|
| `pip install sqlseed` | Base package (SQLite only) |
| `pip install sqlseed[mimesis]` | + Mimesis data engine (recommended) |
| `pip install sqlseed[faker]` | + Faker data engine |
| `pip install "sqlseed[postgres]"` | + PostgreSQL driver (psycopg) |
| `pip install sqlseed[all]` | All data engines + all DB drivers (faker, mimesis, psycopg) + tqdm |
| `pip install sqlseed[docs]` | mkdocs-material + mkdocstrings (this site) |
