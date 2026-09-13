# sqlseed

**Test data for SQLite and PostgreSQL, from your existing schema.**

sqlseed fills existing tables with generated data. It infers rules for common
columns such as names and email addresses, and lets you define application-specific
values and relationships in Python or YAML. Core runs offline; AI is optional.

## Choose how to use it

Use a Python 3.10+ virtual environment and install the entry point you need.
Interface packages install Core as a dependency.

| I want to… | Install | Guide |
| --- | --- | --- |
| Generate data from Python | `python -m pip install sqlseed` | [Python API](api.md) |
| Use a browser | `python -m pip install sqlseed-web` | [Web workbench](web-workbench.md) |
| Work in a terminal | `python -m pip install sqlseed-cli` | [CLI reference](guide.md#cli-reference) |
| Ask a model to suggest or repair rules | `python -m pip install sqlseed-ai` | [AI setup](guide.md#ai-plugin) |
| Use rule-driven MCP tools | `python -m pip install mcp-server-sqlseed` | [MCP setup](guide.md#mcp-server) |

These pages describe the five-package layout introduced in 0.2.4. Upgrading an older
installation? Read the [migration guide](migration.md). For development from source
or optional dependencies, see [installation](guide.md#installation).

## Generate your first data

After installing `sqlseed`, save this as `demo.py` in a new directory and run
`python demo.py`. It creates a SQLite table and adds 100 users, with no repository
checkout or external database server:

```python
import sqlite3
from contextlib import closing

import sqlseed

with closing(sqlite3.connect("demo.db")) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL
        )
    """)
    conn.commit()

result = sqlseed.fill(
    "demo.db",
    table="users",
    count=100,
    provider="faker",
    seed=42,
)
print(result.count, result.errors)  # 100 []
```

Faker is included with Core. Each run appends another 100 rows; it does not clear
the table. Check both `count` and `errors`, because a failed run may retain earlier
committed batches. See [support and maintenance](maintainable-release.md) for
constraint support, write behavior, and reproducibility conditions.

## Try the browser or terminal

With `sqlseed-web` installed, run:

```bash
sqlseed-web
```

Open [http://127.0.0.1:8630](http://127.0.0.1:8630), connect to `demo.db`, select tables,
edit rules, and preview before generating. The command is included with the package;
no custom launcher is required. Follow the [Web guide](web-workbench.md) for details.

With `sqlseed-cli` installed, use the same database:

```bash
sqlseed inspect demo.db --table users --show-mapping
sqlseed preview demo.db -t users -n 5 --provider faker
sqlseed fill demo.db -t users -n 100 --provider faker --no-ai
```

## Next steps

- [User guide](guide.md): YAML rules, generators, expressions, and multi-table configuration.
- [Python API reference](api.md): functions, configuration models, and results.
- [Project walkthrough](project-showcase.md): constraints, failure diagnosis, and replay.
- [AI setup](guide.md#ai-plugin): model configuration and optional rule suggestions.
- [Architecture](architecture.md): package boundaries and extension points.
