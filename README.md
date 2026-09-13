<div align="center">

# 🌱 sqlseed

**Test data for SQLite and PostgreSQL, from your existing schema.**

[English](https://github.com/sunbos/sqlseed/blob/main/README.md) · [简体中文](https://github.com/sunbos/sqlseed/blob/main/README.zh-CN.md)

[![PyPI](https://img.shields.io/pypi/v/sqlseed.svg)](https://pypi.org/project/sqlseed/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/sunbos/sqlseed/actions/workflows/ci.yml/badge.svg)](https://github.com/sunbos/sqlseed/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](https://github.com/sunbos/sqlseed/blob/main/LICENSE)

[Quick start](#quick-start) · [Web workbench](#web-workbench) · [CLI](#command-line) · [Documentation](https://sunbos.github.io/sqlseed/)

</div>

sqlseed fills existing database tables with generated test data. Start with inferred
rules for common columns such as names and email addresses, then specify the ranges,
choices, or relationships your application needs in Python or YAML.

- **Prepare development and test databases:** generate rows in batches and coordinate supported foreign-key dependencies.
- **Keep data rules reusable:** save configuration, preview samples, and use a seed to reproduce a run under the same conditions.
- **Choose your interface:** use the Python API, terminal, browser, or MCP tools. The Core runs offline; AI assistance is optional.

## Choose an entry point

Requires **Python 3.10+**. Use a virtual environment and install the package for the
interface you want; you do not need to install every row below. Interface packages
install Core as a dependency.

| I want to… | Install | Start here |
| --- | --- | --- |
| Generate data from Python | `python -m pip install sqlseed` | [Quick start](#quick-start) |
| Use a browser | `python -m pip install sqlseed-web` | [Web workbench](#web-workbench) |
| Work in a terminal | `python -m pip install sqlseed-cli` | [Command line](#command-line) |
| Ask a model to suggest or repair rules | `python -m pip install sqlseed-ai` | [AI assistance](#optional-ai-assistance) |
| Use rule-driven tools from an MCP client | `python -m pip install mcp-server-sqlseed` | [MCP setup](https://sunbos.github.io/sqlseed/guide/#mcp-server) |

Faker is included with Core and is selected explicitly in the examples below.
Mimesis is optional: install it with `python -m pip install 'sqlseed[mimesis]'`.
For an older installation, see the [upgrade guide](https://sunbos.github.io/sqlseed/migration/).

## Quick start

Install Core in your Python environment:

```bash
python -m pip install sqlseed
```

Save the following as `demo.py` in a new directory and run `python demo.py`.
It creates a SQLite table and adds 100 users. It needs no repository checkout,
API key, or external database server.

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

Names and email addresses are inferred from the columns. The database assigns the
primary keys. Each run appends another 100 rows; it does not clear the table.
Check both `result.count` and `result.errors` after generation.

To inspect samples without writing rows:

```python
rows = sqlseed.preview("demo.db", table="users", count=3, provider="faker")
for row in rows:
    print(row)
```

### Reuse your rules with YAML

For the same `demo.db`, save this as `generate.yaml`. Here the column generators
are explicit, so the rules can be reviewed and reused:

```yaml
db_path: demo.db
provider: faker
locale: en_US
tables:
  - name: users
    count: 100
    seed: 42
    columns:
      - name: name
        generator: name
      - name: email
        generator: email
```

Run it from the same directory:

```python
import sqlseed

for result in sqlseed.fill_from_config("generate.yaml"):
    print(result.count, result.errors)
```

The [configuration guide](https://sunbos.github.io/sqlseed/guide/#yaml-configuration)
covers value ranges, weighted choices, derived columns, and relationships between
tables. See the [generator reference](https://sunbos.github.io/sqlseed/guide/#generators)
for supported names and parameters.

## Web workbench

```bash
python -m pip install sqlseed-web
sqlseed-web
```

Open **[http://127.0.0.1:8630](http://127.0.0.1:8630)**, connect to an existing database
(such as the `demo.db` above), select tables, edit rules, preview, and generate.
The `sqlseed-web` command is installed with the package; no custom startup script
or source checkout is required.

The workbench includes saved configurations, relationship views, and run history.
AI is optional, and manual editing, preview, and generation work without it.
See the [Web guide](https://sunbos.github.io/sqlseed/web-workbench/) for connection
settings, optional components, and deployment requirements.

## Command line

Install the CLI, then use the database created in the quick start:

```bash
python -m pip install sqlseed-cli
sqlseed inspect demo.db --table users --show-mapping
sqlseed preview demo.db -t users -n 5 --provider faker
sqlseed fill demo.db -t users -n 100 --provider faker --no-ai
```

Use `sqlseed --help` or `sqlseed <command> --help` for options. The CLI also supports
configuration templates, snapshots, and replay; see the
[CLI reference](https://sunbos.github.io/sqlseed/guide/#cli-reference).
Installing Core alone provides the Python API; `sqlseed-cli` supplies the `sqlseed`
command.

## PostgreSQL

Install the PostgreSQL driver extra:

```bash
python -m pip install 'sqlseed[postgres]'
```

For an existing database and table, supply the connection URL explicitly:

```python
import sqlseed

result = sqlseed.fill(
    url="postgresql+psycopg://user:password@localhost:5432/app",
    table="users",
    count=100,
    provider="faker",
)
print(result.count, result.errors)
```

Do not pass both a SQLite path and `url`. For supported foreign-key layouts and
entry-point differences, read the [support scope](https://sunbos.github.io/sqlseed/maintainable-release/).

## Optional AI assistance

`sqlseed-ai` adds commands for suggesting generation rules and repairing existing
configurations. Install it, then configure a model backend using the
[AI setup guide](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/README.md).

| Command | Use it to… |
| --- | --- |
| `sqlseed ai-suggest` | Suggest rules for one table |
| `sqlseed ai-analyze` | Analyze selected tables or a database |
| `sqlseed auto-heal` | Repair rules in an existing, structurally valid YAML configuration |

The analysis and repair workflow can infer rules for supported CHECK patterns,
such as enums, ranges, and relationships between columns. Other constraints can
require explicit rules or model suggestions; this is not a solver for arbitrary
SQL CHECK expressions. Review the candidate configuration and verify the data
before relying on it.

See the [AI command reference](https://sunbos.github.io/sqlseed/guide/#ai-suggest)
and [backend and validation guide](https://sunbos.github.io/sqlseed/gemma4-integration/).
For model-assisted MCP tools, use the separate server provided by `sqlseed-ai[mcp]`;
[MCP setup](https://sunbos.github.io/sqlseed/guide/#mcp-server) explains both servers.

## Working with your own database

- **Create tables first.** sqlseed reads existing schemas. Required parent rows must already exist or be generated earlier in the configuration.
- **Check the outcome.** A failed Core or CLI run can retain earlier committed batches. Inspect `count` and `errors` before retrying.
- **Keep reproducibility conditions consistent.** A seed alone does not guarantee identical output across dependency versions, providers, configurations, or initial database contents.

Complex CHECK constraints and composite foreign keys have database-specific limits.
See [support and maintenance](https://sunbos.github.io/sqlseed/maintainable-release/)
for the supported scope and write behavior.

## Documentation

| Next step | Read |
| --- | --- |
| Configure generators, expressions, and multi-table data | [User guide](https://sunbos.github.io/sqlseed/guide/) |
| Use `fill`, `preview`, `connect`, `fill_from_config`, or `load_config` | [Python API reference](https://sunbos.github.io/sqlseed/api/) |
| Try a complete multi-table example | [Order workflow](https://github.com/sunbos/sqlseed/tree/main/examples/order_workflow) |
| Understand package boundaries and extension hooks | [Architecture](https://sunbos.github.io/sqlseed/architecture/) |
| Upgrade an existing installation | [Migration guide](https://sunbos.github.io/sqlseed/migration/) |
| Check published changes | [Releases](https://github.com/sunbos/sqlseed/releases) |

## Contributing

See [CONTRIBUTING.md](https://github.com/sunbos/sqlseed/blob/main/CONTRIBUTING.md) for
source installation, development checks, and contribution guidelines. Report bugs
with a minimal schema, your configuration, package versions, and the full error in
[GitHub Issues](https://github.com/sunbos/sqlseed/issues).

## License

[AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE).
