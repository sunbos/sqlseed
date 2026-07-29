# sqlseed

**Declarative SQLite test data generation toolkit.**

Generate realistic test data for SQLite databases using YAML/JSON config or Python API.
Auto-infers schema, 9-level column mapping, 31 generators, plugin system (pluggy).

## Quick Start

```bash
pip install sqlseed[mimesis]
```

```python
from sqlseed import fill

fill("app.db", table="users", count=100)
```

## CLI

```bash
sqlseed fill app.db -t users -n 10000
sqlseed preview app.db -t users -n 5
sqlseed inspect app.db --show-mapping
```

## Features

- **9-level column mapping strategy** — auto-infers generators from column names
- **31 built-in generators** — names, emails, phones, dates, UUIDs, and more
- **Plugin system** — extend via pluggy hooks
- **Expression engine** — derive columns from other columns (`derive_from` + `expression: "value[-8:]"`)
- **AI-powered schema analysis** — Gemma 4 Native Function Calling (optional)

## Documentation

- [Architecture](architecture.md) — internal design, 9-level mapper, DAG ordering
- [Gemma 4 Integration](gemma4-integration.md) — AI schema analysis setup

## Installation Variants

| Command | Description |
|---------|-------------|
| `pip install sqlseed` | Base package |
| `pip install sqlseed[mimesis]` | + Mimesis data engine (recommended) |
| `pip install sqlseed[faker]` | + Faker data engine |
| `pip install sqlseed[all]` | All data engines + sqlite-utils + tqdm |
| `pip install sqlseed[docs]` | mkdocs-material + mkdocstrings (this site) |
