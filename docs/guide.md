# User Guide

This guide covers installation, quick start, multi-database connections, the
CLI, YAML configuration, the AI plugin, and the MCP server.

For the full Python API, see the [API Reference](api.md). For internal design,
see the [Architecture](architecture.md) page.

---

## Installation

### Install the 0.2.4 release

These pages cover the five-package layout introduced in 0.2.4. The older 0.2.3
release uses different CLI/MCP packaging and lacks interfaces required by the
new plugins. The [migration guide](migration.md) covers upgrading existing
installations and installing a matching artifact set.

Use a fresh Python 3.10+ virtual environment. Choose one installation set:

```bash
python -m venv .venv
# Activate .venv using your shell's activation command.

# Offline Python API
python -m pip install 'sqlseed==0.2.4'

# Core and CLI
python -m pip install 'sqlseed==0.2.4' 'sqlseed-cli==0.2.4'

# All five packages, AI MCP support, and PostgreSQL driver
python -m pip install 'sqlseed[mimesis,postgres]==0.2.4' 'sqlseed-cli==0.2.4' 'sqlseed-ai[mcp]==0.2.4' 'mcp-server-sqlseed==0.2.4' 'sqlseed-web==0.2.4'
python -m pip check
```

Core has no console script. `sqlseed-cli` provides `sqlseed`, `sqlseed-web`
provides `sqlseed-web`, and the rule-driven and AI MCP servers have separate
entry points. Core's `cli` extra is a convenience dependency on `sqlseed-cli`.

Faker is a required Core dependency, and the quick start below selects it
explicitly. Mimesis is optional. The API and CLI default to `mimesis`; Core logs
a warning and falls back to Base if that provider is unavailable. For later
examples that omit the provider or select Mimesis, install
`python -m pip install 'sqlseed[mimesis]==0.2.4'`, or select `faker` in the API,
CLI options, or YAML configuration.

SQLite uses Python's built-in driver. The `postgres` extra installs psycopg 3.
For Core/Web alone, see the [Web guide](web-workbench.md).
The Core `all` extra includes Mimesis, psycopg, tqdm, CLI, and testcontainers;
it does not install AI, MCP, or Web.

### Source installation

Clone the repository and run the relevant command from its root in an activated
Python environment. Supply all required local sibling packages in the same
installation command so they come from the same checkout:

```bash
git clone https://github.com/sunbos/sqlseed.git
cd sqlseed

# Offline Core
python -m pip install -e .

# Core and CLI
python -m pip install -e . -e ./plugins/sqlseed-cli

# Complete workbench and both MCP servers
python -m pip install -e '.[mimesis,postgres]' -e ./plugins/sqlseed-cli -e './plugins/sqlseed-ai[mcp]' -e ./plugins/mcp-server-sqlseed -e ./plugins/sqlseed-web
python -m pip check
```

Choose one set; these commands are alternatives. A source checkout may include
changes beyond a published release. Check the [release list](https://github.com/sunbos/sqlseed/releases)
and [release guide](releasing.md) for package availability and release verification.
To add Mimesis to a minimal source installation, replace `-e .` with
`-e '.[mimesis]'` in the selected command.

### Development and docs

From the repository root, resolve Core and all local plugins together:

```bash
python -m pip install -e '.[dev,all,docs]' -e ./plugins/sqlseed-cli -e './plugins/sqlseed-ai[dev,mcp]' -e ./plugins/mcp-server-sqlseed -e './plugins/sqlseed-web[dev]'
python -m pip check
pytest
ruff check src/ tests/ plugins/
mypy src/sqlseed/ plugins/
```

The `docs` extra installs MkDocs Material and mkdocstrings. `make docs-build`
builds the maintained pages with strict validation.

---

## Quick Start

sqlseed fills existing tables. This first example creates a SQLite database
using Python's standard library, so it works with a PyPI installation and does
not require a repository checkout.

### Python API Quick Start

Save this as `quickstart.py` in a fresh directory and run `python quickstart.py`:

```python
from __future__ import annotations

import sqlite3
from contextlib import closing

import sqlseed

with closing(sqlite3.connect("app.db")) as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            age INTEGER NOT NULL CHECK (age BETWEEN 18 AND 65)
        )
    """)
    db.commit()

result = sqlseed.fill(
    "app.db",
    table="users",
    count=100,
    provider="faker",
    seed=42,
    columns={"age": {"type": "integer", "min_value": 18, "max_value": 65}},
)
print(result.count, result.errors)
# 100 []

with closing(sqlite3.connect("app.db")) as db:
    print(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])
# 100 on the first run
```

Each run appends rows. Check both `count` and `errors`: a failed batch can leave
earlier committed batches. See [write and failure semantics](maintainable-release.md#write-semantics).

sqlseed automatically:

- Skips computed columns and explicit autoincrement primary keys
- Leaves eligible defaulted columns to the database when no earlier rule applies
- Suggests generators from names such as `name`, `email`, and `age`; explicit rules and schema constraints determine the actual values
- Matches `*_at` pattern → datetime values
- Respects column types (`VARCHAR(20)` → max 20-char strings)

### CLI Quick Start

Install `sqlseed-cli` and use the `app.db` created above:

```bash
# Preview 5 rows without writing
sqlseed preview app.db --table users --count 5 --provider faker

# Inspect schema and column mapping strategy
sqlseed inspect app.db --show-mapping

# Append 100 rows using the offline provider
sqlseed fill app.db --table users --count 100 --provider faker --no-ai
```

### Try the Demo Database

For a larger schema, run the repository demo from a source checkout:

```bash
python examples/build_demo_db.py

# Populate the parent referenced by members.org_code first.
sqlseed fill examples/sqlseed_demo.db --table organizations --count 10 --provider faker --no-ai
sqlseed preview examples/sqlseed_demo.db --table members --count 5 --provider faker
sqlseed inspect examples/sqlseed_demo.db --show-mapping
sqlseed fill examples/sqlseed_demo.db --table members --count 100 --provider faker --no-ai
```

---

## Multi-Database Support

sqlseed supports SQLite and PostgreSQL through the same public API. Supported
constraints and write modes differ by database and entry point; see
[support and maintenance](maintainable-release.md) for foreign-key limits and
partial-write semantics.

### Connection URLs

Pass a SQLAlchemy URL instead of a file path to connect to PostgreSQL.

| Database | URL format | Driver |
|----------|-----------|--------|
| SQLite | `sqlite:///path/to/db` or just a file path | built-in `sqlite3` |
| PostgreSQL | `postgresql+psycopg://user:pass@host:5432/db` | `psycopg` (`python -m pip install -e ".[postgres]"`) |

### SQLite

SQLite is the default backend and requires no extra dependencies.

```python
import sqlseed

result = sqlseed.fill("app.db", table="users", count=10_000)
```

### PostgreSQL

```bash
python -m pip install -e ".[postgres]"
```

```python
import sqlseed

result = sqlseed.fill(
    url="postgresql+psycopg://user:password@localhost:5432/mydb",
    table="users",
    count=10_000,
)
```

---

## CLI Reference

The `sqlseed-cli` package provides five subcommands: `fill`, `preview`, `inspect`,
`init`, and `replay`. Installing `sqlseed-ai` adds `ai-suggest`, `ai-analyze`, and
`auto-heal`, for eight commands in a complete installation. Run
`sqlseed --help` to see the full list, or `sqlseed <command> --help` for
per-command options.

### `fill`

Fill a table with generated test data.

```bash
# Basic usage
sqlseed fill app.db --table users --count 10000

# Full parameters
sqlseed fill app.db -t users -n 100000 \
    --provider mimesis \
    --locale en_US \
    --seed 42 \
    --batch-size 10000 \
    --enrich \
    --snapshot

# YAML config-driven (count from config file)
sqlseed fill --config generate.yaml

# Transform script
sqlseed fill app.db -t users -n 10000 --transform transform.py

# Connect via URL instead of file path
sqlseed fill --url "postgresql+psycopg://user:pass@host/db" -t users -n 1000

# Enable debug logging
SQLSEED_LOG_LEVEL=DEBUG sqlseed fill app.db -t users -n 10
```

**Options**

| Option | Description |
|--------|-------------|
| `--table, -t` | Target table name |
| `--count, -n` | Number of rows (required without `--config`) |
| `--provider, -p` | `mimesis` / `faker` / `base` (default: `mimesis`) |
| `--locale, -l` | Locale (default: `en_US`) |
| `--seed, -s` | Random seed for reproducibility |
| `--batch-size, -b` | Rows per batch insert (default: `5000`) |
| `--clear` | Clear table before generating |
| `--config, -c` | YAML/JSON config file path |
| `--transform` | Python transform script path |
| `--snapshot` | Save generation snapshot for replay |
| `--enrich` | Infer distributions from existing data |
| `--no-ai` | Skip AI suggestions |
| `--url` | Database URL (alternative to positional `db_path`) |

### `preview`

Preview generated data without writing to the database.

```bash
sqlseed preview app.db --table users --count 5
sqlseed preview --url "postgresql+psycopg://user:pass@host/db" --table users --count 10
```

**Options**

| Option | Description |
|--------|-------------|
| `--table, -t` | Target table name (required) |
| `--count, -n` | Number of rows to preview (default: `5`) |
| `--provider, -p` | Data provider (default: `mimesis`) |
| `--locale, -l` | Locale (default: `en_US`) |
| `--seed, -s` | Random seed |
| `--url` | Database URL |

### `inspect`

Inspect database schema and column mapping strategies.

```bash
# List all tables
sqlseed inspect app.db

# Inspect a specific table
sqlseed inspect app.db --table users

# View column mapping strategy
sqlseed inspect app.db --table users --show-mapping
```

**Options**

| Option | Description |
|--------|-------------|
| `--table, -t` | Specific table to inspect |
| `--show-mapping` | Show column mapping strategy |
| `--url` | Database URL |

### `init`

Generate a basic YAML configuration skeleton using the database table names.

```bash
sqlseed init generate.yaml --db app.db
```

The template contains the discovered table names, default generation counts,
and empty `columns` lists. Add explicit column rules as needed; omitted rules
are inferred during generation. `--url` accepts a database URL and is mutually
exclusive with `--db`. Without either option, the target defaults to `test.db`.

### `replay`

Replay the generation configuration saved in a snapshot. To compare generated
values, use a fresh database with the same schema, provider and dependency
versions, seed, fixed time ranges, and initial parent data. Replaying into an
already filled database can encounter UNIQUE conflicts; a configuration snapshot
is not a backup of the database. See [reproduction conditions](maintainable-release.md#reproduction-conditions).

```bash
# Generate and save snapshot
sqlseed fill app.db --table users --count 10000 --seed 42 --snapshot
# → Snapshot saved: <cache_dir>/snapshots/YYYY-MM-DD_HHMMSS_ffffff_users.yaml

# Replace this path with the actual snapshot path printed by fill.
sqlseed replay "/path/to/saved-snapshot.yaml"
```

Use cases:

- Reproducible test data in CI/CD pipelines
- Consistent test environments across teams
- Reuse reviewed generation settings during development

### `ai-suggest`

Generate YAML config suggestions using LLM-powered schema analysis. Requires
the `sqlseed-ai` plugin.

```bash
# Install a compatible AI/CLI/Core set as described under Installation

# Select the cloud backend explicitly
export SQLSEED_AI_BACKEND=google_ai_studio
export SQLSEED_AI_API_KEY="your-api-key"

# AI analysis and config generation
sqlseed ai-suggest app.db --table projects --output projects.yaml

# Self-correction is enabled by default (up to 3 retries)
sqlseed ai-suggest app.db --table projects --output projects.yaml --verify

# Specify a model available from the selected backend
sqlseed ai-suggest app.db --table projects --output projects.yaml \
    --model gemma-4-26b-a4b-it

# Use local LM Studio / Ollama (backend selected via environment variable)
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table projects --output projects.yaml \
    --model google/gemma-4-e4b

# Skip cache
sqlseed ai-suggest app.db --table projects --output projects.yaml --no-cache
```

**Options**

| Option | Description |
|--------|-------------|
| `--table, -t` | Target table name |
| `--output, -o` | Output YAML file path |
| `--verify` | Enable self-correction loop (default) |
| `--max-retries` | Self-correction rounds (default: `3`, `0` to disable) |
| `--no-verify` | Skip verification |
| `--no-cache` | Skip cache |
| `--api-key` | LLM API key (overrides `SQLSEED_AI_API_KEY`) |
| `--base-url` | LLM API base URL |
| `--model, -m` | Model name (auto-selected for the configured backend when omitted) |
| `--timeout` | Request timeout in seconds (`0` selects automatically) |
| `--auto-heal` | Process all tables with contract-driven self-healing; ignores `--table` and `--output` |

Select the backend through `SQLSEED_AI_BACKEND` or a recognized base URL.
The AI CLI commands do not accept a `--backend` option.

### `ai-analyze`

Analyze a database or selected tables and write YAML rules. This command uses
`AutoHealOrchestrator` by default; it is distinct from the single-table
`ai-suggest`/`AiConfigRefiner` path.

```bash
sqlseed ai-analyze --db app.db -o rules.yaml
sqlseed ai-analyze --db app.db --tables orders,order_items -o rules.yaml
sqlseed ai-analyze --url 'postgresql+psycopg://user:pass@host/db' -o rules.yaml
```

`--db` and `--url` are mutually exclusive. `--no-dependencies` restricts analysis
to selected tables; `--max-depth` defaults to `5`. `--merge` updates selected
tables in an existing output file and requires `--output`. Without `--output`,
YAML goes to stdout. Model options are `--model`, `--api-key`, `--base-url`, and
`--timeout`; `--max-retries` defaults to `2`. `--log-llm` saves prompt/response
logs for diagnosis.

### `auto-heal`

Repair an existing YAML configuration through contract-driven self-healing:

```bash
sqlseed auto-heal --db app.db --config rules.yaml -o rules_healed.yaml
```

`--config` and one of `--db` or `--url` are required. The two target options are
mutually exclusive and set the target used for the supplied configuration.
`--output` defaults to `<config>_healed.yaml`. `--max-retries` defaults to `3`;
`--model`, `--api-key`, `--base-url`, and `--log-llm` configure the model and logs.
Review the resulting rules and run a preview before executing them.

---

## YAML Configuration

For complex multi-table scenarios, use a YAML config file. This is the most
powerful way to drive sqlseed.

### Basic Structure

The following example appends to existing `users` and `orders` tables. It assumes
`users` has `id`, `name`, and `email`, and `orders.user_id` references `users.id`.

`clear_before` defaults to `false`. If child rows already reference a parent,
clearing that parent first can fail while later tables still append data. Use a
fresh database with the same schema, or explicitly clear dependent child tables
before their parents. Generation order alone does not safely clear an existing
FK graph; inspect every result's `count` and `errors`.

```yaml
# generate.yaml
db_path: "app.db"           # SQLite file path (mutually exclusive with url)
# url: "postgresql+psycopg://user:pass@host/db"  # Mutually exclusive with db_path
provider: mimesis            # mimesis | faker | base | custom
locale: en_US
optimize_pragma: true

tables:
  - name: users
    count: 100000
    batch_size: 10000
    seed: 42
    columns:
      - name: name
        generator: name
      - name: email
        generator: email

  - name: orders
    count: 500000
    columns:
      - name: user_id
        generator: foreign_key
        params:
          ref_table: users
          ref_column: id
          strategy: random

associations: []             # Cross-table column associations
```

### Column Mapping

Each column can be configured in two mutually-exclusive modes:

**Source-column mode** — specify `generator` + `params`:

```yaml
columns:
  - name: email
    generator: email
  - name: age
    generator: integer
    params:
      min_value: 18
      max_value: 65
  - name: status
    generator: choice
    params:
      choices: [active, inactive, banned]
    null_ratio: 0.05         # 5% chance of NULL
```

**Derived-column mode** — specify `derive_from` + `expression`:

```yaml
columns:
  - name: project_no
    generator: pattern
    params:
      regex: "PRJ-\\d{6}"
    constraints:
      unique: true

  - name: short_code
    derive_from: project_no    # depends on project_no
    expression: "value[-6:]"  # last 6 chars
    constraints:
      unique: true
```

sqlseed builds a column dependency DAG and topologically sorts columns before
generation. If a derived column's unique constraint fails, sqlseed backtracks
and regenerates the source column.

### Generators

sqlseed ships with <!-- BEGIN:AUTO-GENERATED:generator-count -->36<!-- END:AUTO-GENERATED:generator-count --> built-in generators.
The complete table below also includes `foreign_key` and `skip`, which the
orchestration layer handles separately.

| Generator | Description | Example Parameters |
|-----------|-------------|-------------------|
| `string` | Random string | `min_length`, `max_length`, `charset` |
| `integer` | Integer | `min_value`, `max_value` |
| `float` | Float | `min_value`, `max_value`, `precision` |
| `boolean` | Boolean | — |
| `name` | Full name | — |
| `first_name` | First name | — |
| `last_name` | Last name | — |
| `email` | Email address | — |
| `phone` | Phone number | — |
| `address` | Address | — |
| `company` | Company name | — |
| `url` | URL | — |
| `ipv4` | IPv4 address | — |
| `uuid` | UUID | — |
| `date` | Date | `start_date`, `end_date`, `weekdays` |
| `datetime` | Datetime | `start_date`, `end_date`, `all_day`, `start_time`, `end_time`, `weekdays` |
| `time` | Time | `all_day`, `start_time`, `end_time` |
| `timestamp` | Unix timestamp | same as `datetime` |
| `text` | Long text | `min_length`, `max_length` |
| `sentence` | Sentence | — |
| `word` | Real English word | — |
| `password` | Password | `length` |
| `choice` | Pick from list | `choices` |
| `json` | JSON string | `schema` |
| `pattern` | Regex match | `regex` |
| `bytes` | Binary data | `length` |
| `username` | Username | — |
| `city` | City | — |
| `country` | Country | — |
| `state` | State/Province | — |
| `zip_code` | Zip/Postal code | — |
| `job_title` | Job title | — |
| `country_code` | Country code | — |
| `catch_phrase` | Business catch phrase (multi-word) | — |
| `template` | Formatted string with placeholders | `template`, `sequence_start`, `sequence_step` |
| `weighted_choice` | Weighted random pick | `choices` (list of `{value, weight}`) or `weighted_choices` (dict) |
| `foreign_key` | FK reference | `ref_table`, `ref_column`, `strategy` |
| `skip` | Skip (use default/NULL) | — |

The `float` generator treats `min_value` and `max_value` as inclusive bounds,
including after rounding to `precision` decimal places. Reversed or non-finite
bounds raise `ValueError`. If no value with the requested precision fits the
range (for example, `0.005`–`0.006` with `precision: 2`), generation raises
`ValueError` instead of returning an out-of-range value.

`foreign_key` and `skip` are special pseudo-generators: they are handled
directly by the `RelationResolver` / `DataStream` and are not registered in
`GENERATOR_MAP`.

### Constraints

Per-column constraints live under `constraints`:

```yaml
columns:
  - name: project_no
    generator: pattern
    params:
      regex: "PRJ-\\d{6}"
    constraints:
      unique: true             # enforce uniqueness with backtracking
      max_retries: 100         # default: 100
  - name: age
    generator: integer
    constraints:
      min_value: 18
      max_value: 65
```

### Expressions

The expression engine supports 26 safe functions plus slicing and basic
arithmetic. Expressions are sandboxed via `simpleeval` with a 5-second timeout.
`import`, `exec`, and file I/O are not allowed.

| Function | Usage | Description |
|----------|-------|-------------|
| `len(s)` | `len(value)` | Length |
| `int(s)` | `int(value)` | To integer |
| `str(s)` | `str(value)` | To string |
| `float(s)` | `float(value)` | To float |
| `hex(n)` | `hex(value)` | To hexadecimal |
| `oct(n)` | `oct(value)` | To octal |
| `bin(n)` | `bin(value)` | To binary |
| `abs(n)` | `abs(value)` | Absolute value |
| `min(*args)` | `min(a, b)` | Minimum |
| `max(*args)` | `max(a, b)` | Maximum |
| `round(n, ndigits)` | `round(value, 2)` | Round to N digits |
| `upper(s)` | `upper(value)` | Uppercase |
| `lower(s)` | `lower(value)` | Lowercase |
| `strip(s)` | `strip(value)` | Trim both ends |
| `lstrip(s)` | `lstrip(value)` | Trim left |
| `rstrip(s)` | `rstrip(value)` | Trim right |
| `zfill(s, width)` | `zfill(value, 10)` | Zero-fill |
| `replace(s, old, new)` | `replace(value, "-", "")` | Replace |
| `substr(s, start, end)` | `substr(value, 0, 8)` | Substring |
| `lpad(s, width, char)` | `lpad(value, 8, "0")` | Left-pad |
| `rpad(s, width, char)` | `rpad(value, 8, "0")` | Right-pad |
| `concat(*args)` | `concat("PRE_", value)` | Concatenate |
| `random_float(min, max)` | `random_float(0, value)` | Random float in range |
| `random_int(min, max)` | `random_int(1, 100)` | Random integer in range |
| `random_choice(seq)` | `random_choice([1,2,3])` | Random element from sequence |
| `timedelta(...)` | `value + timedelta(days=7)` | Date arithmetic (`days`/`seconds`/`hours`/`minutes`/`weeks`) |
| Slicing | `value[-8:]` | Python slice syntax |
| Math | `value * 2 + 1` | Basic arithmetic |

### Cross-Table Associations

The **SharedPool** can reuse values already registered from primary-key and
foreign-key columns in the current orchestration session. Merely giving ordinary
columns the same name (for example, `member_no`) does not establish a relationship.
UNIQUE non-FK target columns also avoid implicit reuse.

Use actual database foreign keys for declared relationships. When a relationship
is not represented by an FK, declare it explicitly via `associations`, including
the source table, source column, and target tables:

For example, create these tables before running the configuration. The
relationship is declared in the configuration; this DDL has no FK constraint:

```sql
CREATE TABLE departments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
CREATE TABLE employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL,
    name TEXT NOT NULL
);
```

```yaml
db_path: "app.db"
provider: mimesis

tables:
  - name: departments
    count: 5
  - name: employees
    count: 20

associations:
  - column_name: department_id     # column name in the target table
    source_table: departments      # source table providing values
    source_column: id              # column name in source table (defaults to column_name)
    target_tables:                 # target tables using this association
      - employees
    strategy: shared_pool          # shared_pool | random
```

### Transform Scripts

For complex business logic that can't be expressed declaratively, write a
Python transform script:

The script below expects an existing `users` table with `age` and `phone`
columns. Add the column that will store its result before generating data:

```sql
ALTER TABLE users ADD COLUMN vip_level INTEGER;
```

```python
# transform_users.py
def transform_row(row, ctx):
    """Called for every generated row."""
    age = row.get("age", 0)
    if age >= 60:
        row["vip_level"] = 3
    elif age >= 40:
        row["vip_level"] = 2
    else:
        row["vip_level"] = 1

    phone = row.get("phone", "")
    if phone and not phone.startswith("+1"):
        row["phone"] = f"+1{phone}"

    return row
```

Use it from the CLI:

```bash
sqlseed fill app.db --table users --count 10000 --transform transform_users.py
```

Or in YAML:

```yaml
db_path: "app.db"
tables:
  - name: users
    count: 10000
    transform: "./transform_users.py"
```

---

## AI Plugin

The `sqlseed-ai` plugin uses LLMs to analyze database schema semantics and
auto-generate YAML config suggestions with a self-correction loop.

### Setup

Install the compatible Core/CLI/AI set described under [Installation](#installation).
Choose a backend explicitly, or provide a base URL that can identify it:

```bash
# Google AI Studio
export SQLSEED_AI_BACKEND=google_ai_studio
export GOOGLE_API_KEY="your-api-key"

# Alternatively, configure an OpenAI-compatible endpoint
# export SQLSEED_AI_BACKEND=openai_compat
# export SQLSEED_AI_BASE_URL="https://your-provider.example/v1"
# export SQLSEED_AI_MODEL="your-model-id"
# export SQLSEED_AI_API_KEY="your-api-key"
```

### Usage

```bash
# Basic AI suggestion
sqlseed ai-suggest app.db --table projects --output projects.yaml

# With self-correction loop (3 rounds by default)
sqlseed ai-suggest app.db --table projects --output projects.yaml --verify

# Disable self-correction
sqlseed ai-suggest app.db --table projects --output projects.yaml --max-retries 0
```

### Backends

sqlseed-ai supports the backends below. An explicit `SQLSEED_AI_BACKEND` takes
priority, followed by recognized base URL patterns. Otherwise the backend is
`openai_compat`, which requires an explicit base URL. Setting a Google API key
alone does not select Google AI Studio.

| Backend | Description | Suitable for |
|---------|-------------|--------------|
| `google_ai_studio` | Explicit Google AI Studio API selection | Models available from that service |
| `lm_studio` | Local inference via LM Studio | Gemma 4 2B/4B |
| `ollama` | Local inference via Ollama | Gemma 4 2B/4B/26B |
| `openai_compat` | Generic OpenAI-compatible endpoint; fallback backend | Models available from the configured endpoint |

Model IDs depend on the backend. When omitted, local backends try to detect a
loaded model before using the local Gemma E4B fallback; cloud backends use the
registered Gemma 26B model ID for that backend. An ID in the project registry is
not a guarantee that a service currently hosts it. Set an available model
explicitly when needed and verify a small request.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SQLSEED_AI_API_KEY` | LLM API key |
| `SQLSEED_AI_BASE_URL` | LLM API base URL |
| `SQLSEED_AI_MODEL` | Explicit model ID; otherwise selected for the resolved backend |
| `SQLSEED_AI_BACKEND` | Explicit backend; fallback without a recognized URL is `openai_compat` |
| `SQLSEED_AI_TOOL_CALLING_PROTOCOL` | `gemma4`, `openai`, or `none`; resolved against backend support |
| `SQLSEED_AI_TIMEOUT` | Request timeout in seconds (`0` selects automatically) |
| `GOOGLE_API_KEY` | API-key fallback after `SQLSEED_AI_API_KEY`, before `OPENAI_API_KEY` |
| `OPENAI_API_KEY` | Fallback API key |
| `OPENAI_BASE_URL` | Fallback base URL |

### AI Workflow

The single-table `ai-suggest` path uses `SchemaAnalyzer` and `AiConfigRefiner`:

1. Extract schema context (columns, indexes, sample data, FKs, distribution)
2. Build LLM prompt with few-shot examples
3. LLM returns JSON column config suggestions
4. `AiConfigRefiner` auto-validates config correctness
5. If errors are found (unknown generator, type mismatch, etc.), a correction
   request is sent to the LLM
6. Up to 3 self-correction rounds; outputs a validated YAML config

`ai-analyze` and `auto-heal` use `AutoHealOrchestrator` for contract-driven
analysis or repair. The Web assistant provides suggestions for review; it does
not automatically execute accepted rules or run the CLI.

For details on Gemma 4 Native Function Calling, see the
[Gemma 4 Integration](gemma4-integration.md) page.

---

## MCP Server

The `mcp-server-sqlseed` package exposes sqlseed to AI assistants (Claude,
Cursor, etc.) via the [Model Context Protocol](https://modelcontextprotocol.io/).

### Setup

Use the compatible package set from [Installation](#installation). The rule-driven
server comes from `mcp-server-sqlseed`; the AI server requires `sqlseed-ai[mcp]`.
They run as independent processes. Installing the AI package does not add tools
to an already configured rule-driven server.

```bash
# Rule-driven server (offline)
mcp-server-sqlseed

# AI server (a separate process, normally started by the MCP client)
mcp-server-sqlseed-ai
```

### Configure MCP Client

A client using both tool sets needs both server entries. For example, in Claude
Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    },
    "sqlseed-ai": {
      "command": "mcp-server-sqlseed-ai",
      "env": {
        "SQLSEED_AI_BACKEND": "lm_studio",
        "SQLSEED_AI_MODEL": "google/gemma-4-e4b"
      }
    }
  }
}
```

Use executable paths from the chosen environment if the client cannot find them.
The AI example requires a reachable LM Studio service with the configured model.
For cloud or other backends, replace its environment settings using the AI setup
above; a running MCP process alone does not verify model connectivity.

### Tools

The base `mcp-server-sqlseed` package ships two rule-driven tools (no LLM):

| Type | Name | Description |
|------|------|-------------|
| 🤖 Tool | `sqlseed_generate_yaml` | Rule-driven YAML config generation via `ColumnMapper` (offline, deterministic, no LLM) |
| ⚡ Tool | `sqlseed_execute_fill` | Execute data generation (supports YAML config string, includes `enrich`) |

The separate `mcp-server-sqlseed-ai` process exposes four AI tools:

| Type | Name | Description |
|------|------|-------------|
| 🤖 Tool | `sqlseed_ai_generate_yaml` | LLM-driven YAML config generation (semantic schema analysis) |
| 🧠 Tool | `sqlseed_gemma4_analyze` | Analyze schema with the configured model and supported response protocol |
| 🧠 Tool | `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow (analyze → config → fill) |
| 🧠 Tool | `sqlseed_list_gemma_models` | List registered Gemma 4 variants, hardware compatibility, and backend status |

### Example Interaction

Once configured, you can tell your AI assistant:

> "Analyze the structure of the `projects` table in `app.db`, generate a YAML
> config, then fill 5000 rows."

With both servers configured, the assistant can request rules from
`sqlseed_ai_generate_yaml` and submit reviewed rules to `sqlseed_execute_fill`.
With only the rule-driven server configured, use `sqlseed_generate_yaml` for
offline rules. Review the database target and rules before requesting a fill.

---

## 9-Level Smart Column Mapping

One of sqlseed's core highlights is the `ColumnMapper`'s 9-level strategy chain.
Each column is matched by priority:

```
Level 1 │ Computed / explicit autoincrement PK → skip
        ▼
Level 2 │ Explicit user config
        ▼
        │ SQLite rowid alias → skip; other integer PK → type fallback
        ▼
Level 3 │ Exact match         Custom rules, then 75 built-in rules
        ▼
Level 4 │ DEFAULT handling    skip / __enrich__ / forced type inference
        ▼
Level 5 │ Pattern match       Custom rules, then 29 built-in patterns
        ▼
Level 6 │ Snake-case retry    Convert CamelCase, retry exact rules
        ▼
Level 7 │ Snake-case retry    Retry pattern rules
        ▼
Level 8 │ NULLABLE fallback   skip / __enrich__ / forced type inference
        ▼
Level 9 │ Type fallback       Preserve declared string and byte lengths
```

Adapters distinguish SQLite rowid aliases from composite, descending, and
WITHOUT ROWID primary keys. ID-like names alone do not establish a foreign-key
relationship. Within exact or pattern matching, custom rules precede built-ins.

What this means in practice:

- `user_email` → Level 5 pattern `*_email` → `email` generator
- `is_verified` → Level 5 pattern `is_*` → `boolean` generator
- `userEmail` → snake-case retry → `user_email` → Level 7 pattern
- Unmatched non-null `VARCHAR(20)` → Level 9 → max 20-character string
- Column with `DEFAULT 1` and no earlier rule → Level 4 → skip generation
- `gender` with `DEFAULT 'male'` → Level 3 exact match → `choice` (before DEFAULT)

---

## Plugin System

sqlseed declares 12 hook contracts via [pluggy](https://pluggy.readthedocs.io/).
Their current invocation points are listed below; a declared hook is not necessarily
dispatched by the normal generation pipeline.

| Hook | firstresult | Trigger |
|------|:-----------:|--------|
| `sqlseed_register_providers` | | Register custom data providers |
| `sqlseed_register_column_mappers` | | Register custom column mapping rules |
| `sqlseed_ai_analyze_table` | ✓ | AI analyzes table schema (returns column config) |
| `sqlseed_apply_ai_suggestions` | ✓ | High-level AI mediation (orchestrator entry; implemented in `sqlseed_ai.ai_mediator`) |
| `sqlseed_pre_generate_templates` | ✓ | AI pre-computes candidate value pools |
| `sqlseed_before_generate` | | Before data generation loop |
| `sqlseed_after_generate` | | After data generation completes |
| `sqlseed_transform_row` | | Declared hookspec; not dispatched by normal Core generation |
| `sqlseed_transform_batch` | | Each implementation receives the same input batch; the last non-None result is selected |
| `sqlseed_before_insert` | | Before each batch write to DB |
| `sqlseed_after_insert` | | After each batch write to DB |
| `sqlseed_shared_pool_loaded` | | After SharedPool registration (pool readable) |

### Custom Provider Example

```python
# my_provider.py
from __future__ import annotations
from typing import Any

from sqlseed.generators import UnknownGeneratorError

class MyCustomProvider:
    """Just implement the DataProvider Protocol. No base class required."""

    def __init__(self) -> None:
        self._locale: str = "en_US"

    @property
    def name(self) -> str:
        return "my_custom"

    def set_locale(self, locale: str) -> None:
        self._locale = locale

    def set_seed(self, seed: int) -> None:
        ...

    def generate(self, type_name: str, **params: Any) -> Any:
        if type_name == "string":
            return "custom_string"
        if type_name == "email":
            return "user@example.com"
        raise UnknownGeneratorError(type_name)
```

**Registration via entry-point (recommended):**

```toml
# pyproject.toml
[project.entry-points."sqlseed"]
my_custom = "my_provider:MyCustomProvider"
```

**Registration via plugin hook:**

```python
from sqlseed.plugins.hookspecs import hookimpl

class MyPlugin:
    @hookimpl
    def sqlseed_register_providers(self, registry):
        from my_provider import MyCustomProvider
        registry.register(MyCustomProvider())
```

---

## Troubleshooting

### Enable Debug Logging

```bash
SQLSEED_LOG_LEVEL=DEBUG sqlseed fill app.db -t users -n 10
```

### Common Issues

**`--count is required when not using --config`**

Provide `--count` (or `-n`) when using `sqlseed fill` without `--config`.

**`Cannot specify both positional db_path and --url`**

`db_path` and `--url` are mutually exclusive. Use one or the other.

**`Table does not exist`**

Inspect the database first with `sqlseed inspect app.db` to verify the table
name and its reflected spelling. Identifier case handling depends on the
database and quoting rules, not simply on the operating system.

**`Unknown generator: <name>`**

Check the generator name against the [Generators](#generators) table above.
Custom generators must be registered via entry-point or plugin hook.

**AI plugin not found**

Install a compatible Core/CLI/AI set using the [installation guide](#installation).
From a source checkout, supply all three local packages in one command:

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e ./plugins/sqlseed-ai
```

When `sqlseed-ai` is not installed, `sqlseed ai-suggest` fails with click's
`No such command` error. If the plugin is installed but fails to load, the
CLI emits a `WARNING` log instead.

---

## Next Steps

- [API Reference](api.md) — Full Python API documentation
- [Architecture](architecture.md) — Internal design and module structure
- [Gemma 4 Integration](gemma4-integration.md) — AI schema analysis setup
