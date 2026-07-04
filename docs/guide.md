# User Guide

This guide covers installation, quick start, multi-database connections, the
CLI, YAML configuration, the AI plugin, and the MCP server.

For the full Python API, see the [API Reference](api.md). For internal design,
see the [Architecture](architecture.md) page.

---

## Installation

### Basic Installation

```bash
pip install sqlseed
```

This installs the core package with SQLite support out of the box. No database
drivers are required for SQLite.

### Data Engine Installation

sqlseed supports three data engines. Mimesis is recommended for performance and
locale coverage; Faker is a popular alternative with a rich ecosystem.

```bash
# Recommended: Mimesis (high performance, great locale support)
pip install sqlseed[mimesis]

# Optional: Faker (rich ecosystem)
pip install sqlseed[faker]

# Install all data engines + all database drivers + tqdm
pip install sqlseed[all]
```

### Database Backend Installation

sqlseed supports SQLite (default) and PostgreSQL via SQLAlchemy.

```bash
# PostgreSQL support (psycopg driver)
pip install "sqlseed[postgres]"

# All database backends + all data engines
pip install "sqlseed[all]"
```

!!! note "SQLite requires no extra dependencies"

    SQLite works out of the box using Python's built-in `sqlite3` module.
    PostgreSQL drivers are only required when connecting to PostgreSQL
    databases.

### AI Plugin Installation

The `sqlseed-ai` plugin adds LLM-powered schema analysis. It uses Gemma 4
Native Function Calling and supports multiple backends.

```bash
# AI analysis plugin (requires openai SDK)
pip install sqlseed-ai
```

### MCP Server Installation

The `mcp-server-sqlseed` package exposes sqlseed to AI assistants (Claude,
Cursor, etc.) via the Model Context Protocol.

```bash
# MCP server (requires mcp SDK)
pip install mcp-server-sqlseed

# MCP server + AI support (all-in-one)
pip install mcp-server-sqlseed[ai]
```

### Docs Build (Developers)

```bash
pip install sqlseed[docs]   # mkdocs-material + mkdocstrings
```

### Full Dev Environment

```bash
git clone https://github.com/sunbos/sqlseed.git
cd sqlseed

# Install core + all providers + dev dependencies
pip install -e ".[dev,all]"

# Optional plugins
pip install -e "./plugins/sqlseed-ai"
pip install -e "./plugins/mcp-server-sqlseed"

# Verify installation
pytest
ruff check src/ tests/
mypy src/sqlseed/
```

---

## Quick Start

### CLI Quick Start

```bash
# Fill 10,000 rows into the users table
sqlseed fill app.db --table users --count 10000

# Preview 5 rows without writing
sqlseed preview app.db --table users --count 5

# Inspect schema and column mapping strategy
sqlseed inspect app.db --show-mapping
```

### Python API Quick Start

```python
import sqlseed

# One line fills 10,000 rows of high-quality test data
result = sqlseed.fill("app.db", table="users", count=10_000)
print(result)
# → GenerationResult(table=users, count=10000, elapsed=0.52s, speed=19230 rows/s)
```

sqlseed automatically:

- Skips `id` (autoincrement primary key)
- Skips columns with default values
- Infers `name` → real names, `email` → email addresses, `age` → integers 18–100
- Matches `*_at` pattern → datetime values
- Respects column types (`VARCHAR(20)` → max 20-char strings)

### Try the Demo Database

```bash
python examples/build_demo_db.py

sqlseed preview examples/sqlseed_demo.db --table members --count 5
sqlseed inspect examples/sqlseed_demo.db --show-mapping
sqlseed fill examples/sqlseed_demo.db --table members --count 100
```

---

## Multi-Database Support

sqlseed supports SQLite and PostgreSQL. The same API works across
both databases — schema inference, FK resolution, expression engine, and
plugin hooks all run identically.

### Connection URLs

Pass a SQLAlchemy URL instead of a file path to connect to PostgreSQL.

| Database | URL format | Driver |
|----------|-----------|--------|
| SQLite | `sqlite:///path/to/db` or just a file path | built-in `sqlite3` |
| PostgreSQL | `postgresql+psycopg://user:pass@host:5432/db` | `psycopg` (`pip install sqlseed[postgres]`) |

### SQLite

SQLite is the default backend and requires no extra dependencies.

```python
import sqlseed

result = sqlseed.fill("app.db", table="users", count=10_000)
```

### PostgreSQL

```bash
pip install "sqlseed[postgres]"
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

The `sqlseed` CLI is built with `click` and provides six subcommands. Run
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
    --clear \
    --enrich \
    --snapshot

# YAML config-driven (count from config file)
sqlseed fill --config generate.yaml

# Transform script
sqlseed fill app.db -t users -n 10000 --transform transform.py

# Connect via URL instead of file path
sqlseed fill --url "postgresql://user:pass@host/db" -t users -n 1000

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
sqlseed preview --url "postgresql://..." --table users --count 10
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

Generate a YAML config template from an existing database schema.

```bash
sqlseed init generate.yaml --db app.db
```

The generated template includes all tables and columns discovered in the
database, ready for you to edit and feed back to `sqlseed fill --config`.

### `replay`

Replay a previously saved snapshot to reproduce a generation run exactly.

```bash
# Generate and save snapshot
sqlseed fill app.db --table users --count 10000 --seed 42 --snapshot
# → Snapshot saved: <cache_dir>/snapshots/YYYY-MM-DD_HHMMSS_users.yaml

# Replay anytime
sqlseed replay <cache_dir>/snapshots/YYYY-MM-DD_HHMMSS_users.yaml
```

Use cases:

- Reproducible test data in CI/CD pipelines
- Consistent test environments across teams
- Quick database state reconstruction during development

### `ai-suggest`

Generate YAML config suggestions using LLM-powered schema analysis. Requires
the `sqlseed-ai` plugin.

```bash
# Install AI plugin
pip install sqlseed-ai

# Set API key
export SQLSEED_AI_API_KEY="your-api-key"

# AI analysis and config generation
sqlseed ai-suggest app.db --table projects --output projects.yaml

# AI suggestions with self-correction (3 rounds by default)
sqlseed ai-suggest app.db --table projects --output projects.yaml --verify

# Specify model (defaults to Gemma 4 26B via Google AI Studio)
sqlseed ai-suggest app.db --table projects --output projects.yaml \
    --model gemma-4-26b-a4b-it

# Use local LM Studio / Ollama
sqlseed ai-suggest app.db --table projects --output projects.yaml \
    --backend lm_studio --model google/gemma-4-e4b

# Skip cache
sqlseed ai-suggest app.db --table projects --output projects.yaml --no-cache
```

**Options**

| Option | Description |
|--------|-------------|
| `--table, -t` | Target table name |
| `--output, -o` | Output YAML file path |
| `--verify` | Enable self-correction loop |
| `--max-retries` | Self-correction rounds (default: `3`, `0` to disable) |
| `--no-verify` | Skip verification |
| `--no-cache` | Skip cache |
| `--api-key` | LLM API key (overrides `SQLSEED_AI_API_KEY`) |
| `--base-url` | LLM API base URL |
| `--model` | Model name (default: Gemma 4 26B) |
| `--backend` | `google_ai_studio` / `lm_studio` / `ollama` / `openai_compat` |

---

## YAML Configuration

For complex multi-table scenarios, use a YAML config file. This is the most
powerful way to drive sqlseed.

### Basic Structure

```yaml
# generate.yaml
db_path: "app.db"           # SQLite file path (mutually exclusive with url)
# url: "postgresql://..."   # Database URL (mutually exclusive with db_path)
provider: mimesis            # mimesis | faker | base | custom
locale: en_US
optimize_pragma: true

tables:
  - name: users
    count: 100000
    batch_size: 10000
    clear_before: true
    seed: 42
    columns:
      - name: username
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

sqlseed ships with 32 built-in generators. The most common ones:

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
| `date` | Date | `start_year`, `end_year` |
| `datetime` | Datetime | `start_year`, `end_year` |
| `timestamp` | Unix timestamp | — |
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
| `foreign_key` | FK reference | `ref_table`, `ref_column`, `strategy` |
| `skip` | Skip (use default/NULL) | — |

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
| Slicing | `value[-8:]` | Python slice syntax |
| Math | `value * 2 + 1` | Basic arithmetic |

### Cross-Table Associations

When two tables share a column name (e.g. `member_no`), sqlseed automatically
maintains cross-table consistency via the **SharedPool** mechanism — no config
needed.

When the target column name differs from the source (e.g. `department_id` →
`id`), or there's no FK constraint but you need an association, declare it
explicitly via `associations`:

```yaml
db_path: "app.db"
provider: mimesis

tables:
  - name: departments
    count: 5
    clear_before: true
  - name: employees
    count: 20
    clear_before: true

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

```bash
# Install the AI plugin
pip install sqlseed-ai

# Set API key (one of the following)
export SQLSEED_AI_API_KEY="your-api-key"
# or
export OPENAI_API_KEY="your-api-key"
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

sqlseed-ai supports multiple backends for Gemma 4 models. Set the backend via
`--backend` or the `SQLSEED_AI_BACKEND` environment variable.

| Backend | Description | Suitable for |
|---------|-------------|--------------|
| `google_ai_studio` | Official Google AI Studio API (default) | Gemma 4 26B/31B |
| `lm_studio` | Local inference via LM Studio | Gemma 4 2B/4B |
| `ollama` | Local inference via Ollama | Gemma 4 2B/4B/26B |
| `openai_compat` | Generic OpenAI-compatible endpoint (OpenRouter, DeepSeek, etc.) | Any |

!!! tip "Free models via OpenRouter"

    For users without a paid API key, OpenRouter provides free models. Set:
    ```bash
    export SQLSEED_AI_BACKEND=openai_compat
    export SQLSEED_AI_BASE_URL=https://openrouter.ai/api/v1
    export SQLSEED_AI_MODEL=<free-model-name>
    ```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SQLSEED_AI_API_KEY` | LLM API key |
| `SQLSEED_AI_BASE_URL` | LLM API base URL |
| `SQLSEED_AI_MODEL` | Model name (default: Gemma 4 26B) |
| `SQLSEED_AI_BACKEND` | Backend (default: `google_ai_studio`) |
| `OPENAI_API_KEY` | Fallback API key |
| `OPENAI_BASE_URL` | Fallback base URL |

### AI Workflow

1. Extract schema context (columns, indexes, sample data, FKs, distribution)
2. Build LLM prompt with few-shot examples
3. LLM returns JSON column config suggestions
4. `AiConfigRefiner` auto-validates config correctness
5. If errors are found (unknown generator, type mismatch, etc.), a correction
   request is sent to the LLM
6. Up to 3 self-correction rounds; outputs a validated YAML config

For details on Gemma 4 Native Function Calling, see the
[Gemma 4 Integration](gemma4-integration.md) page.

---

## MCP Server

The `mcp-server-sqlseed` package exposes sqlseed to AI assistants (Claude,
Cursor, etc.) via the [Model Context Protocol](https://modelcontextprotocol.io/).

### Setup

```bash
# Install MCP server
pip install mcp-server-sqlseed

# All-in-one: MCP server + AI support
pip install mcp-server-sqlseed[ai]

# Manual start (usually managed by MCP client)
python -m mcp_server_sqlseed
```

### Configure MCP Client

Claude Desktop example (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    }
  }
}
```

### Tools

| Type | Name | Description |
|------|------|-------------|
| 📖 Resource | `sqlseed://schema/{db_path}/{table_name}` | Get table schema as JSON |
| 🔍 Tool | `sqlseed_inspect_schema` | Inspect schema (columns, FK, indexes, samples, schema_hash) |
| 🤖 Tool | `sqlseed_generate_yaml` | AI-driven YAML config generation with self-correction |
| ⚡ Tool | `sqlseed_execute_fill` | Execute data generation (supports YAML config string, includes `enrich`) |
| 🧠 Tool | `sqlseed_gemma4_analyze` | Analyze schema using Gemma 4 with Native Function Calling |
| 🧠 Tool | `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow (analyze → config → fill) |
| 🧠 Tool | `sqlseed_list_gemma_models` | List available Gemma 4 models and backend status |

### Example Interaction

Once configured, you can tell your AI assistant:

> "Analyze the structure of the `projects` table in `app.db`, generate a YAML
> config, then fill 5000 rows."

The AI assistant will call `sqlseed_inspect_schema` →
`sqlseed_generate_yaml` → `sqlseed_execute_fill` in sequence, without you
writing any code.

---

## 9-Level Smart Column Mapping

One of sqlseed's core highlights is the `ColumnMapper`'s 9-level strategy chain.
Each column is matched by priority:

```
Level 1 │ Autoincrement PK    PK + AUTOINCREMENT / INTEGER → skip
        ▼
Level 2 │ User config         columns={"email": "email"} highest priority
        ▼
Level 3 │ Custom exact match  Rules registered via plugin hooks
        ▼
Level 4 │ Built-in exact      74 rules: email→email, phone→phone, age→integer...
        ▼
Level 5 │ DEFAULT check        Has default → skip / __enrich__ (when enrich=True)
        ▼
Level 6 │ Custom pattern       Regex rules registered via plugin hooks
        ▼
Level 7 │ Built-in pattern     27 regexes: *_at→datetime, *_id→foreign_key, is_*→boolean...
        ▼
Level 8 │ NULLABLE fallback    Nullable → skip / __enrich__
        ▼
Level 9 │ Type-faithful        VARCHAR(32)→max 32 chars, INT8→0~255, BLOB(1024)→1024 bytes
```

What this means in practice:

- Column `user_email` → Level 7 pattern `*_email` → `email` generator
- Column `is_verified` → Level 7 pattern `is_*` → `boolean` generator
- Column type `VARCHAR(20)` → Level 9 type fallback → max 20-char string
- Column with `DEFAULT 1` → Level 5 → skip generation
- Column `gender` with `DEFAULT 'male'` → Level 4 exact match → `choice` generator (exact match takes priority over DEFAULT)

---

## Plugin System

sqlseed provides 12 hook points via [pluggy](https://pluggy.readthedocs.io/),
covering the full data generation lifecycle:

| Hook | firstresult | Trigger |
|------|:-----------:|--------|
| `sqlseed_register_providers` | | Register custom data providers |
| `sqlseed_register_column_mappers` | | Register custom column mapping rules |
| `sqlseed_ai_analyze_table` | ✓ | AI analyzes table schema (returns column config) |
| `sqlseed_apply_ai_suggestions` | ✓ | High-level AI mediation (orchestrator entry; implemented in `sqlseed_ai.ai_mediator`) |
| `sqlseed_pre_generate_templates` | ✓ | AI pre-computes candidate value pools |
| `sqlseed_before_generate` | | Before data generation loop |
| `sqlseed_after_generate` | | After data generation completes |
| `sqlseed_transform_row` | | Per-row transform (hot path, mind performance) |
| `sqlseed_transform_batch` | | Per-batch transform (supports chaining) |
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
name. Table names are case-sensitive on Linux.

**`Unknown generator: <name>`**

Check the generator name against the [Generators](#generators) table above.
Custom generators must be registered via entry-point or plugin hook.

**AI plugin not found**

Install the AI plugin separately:

```bash
pip install sqlseed-ai
```

The CLI silently degrades when `sqlseed-ai` is missing — `ai-suggest` will
report that the plugin is required.

---

## Next Steps

- [API Reference](api.md) — Full Python API documentation
- [Architecture](architecture.md) — Internal design and module structure
- [Gemma 4 Integration](gemma4-integration.md) — AI schema analysis setup
