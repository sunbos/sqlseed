<div align="center">

# 🌱 sqlseed

**[English](README.md)** | [中文](README.zh-CN.md)

### Declarative SQLite Test Data Generation Toolkit

**One line of code, tens of thousands of rows. Zero-config smart generation, AI-powered precision tuning.**

[![CI](https://github.com/sunbos/sqlseed/actions/workflows/ci.yml/badge.svg)](https://github.com/sunbos/sqlseed/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab.svg?logo=python\&logoColor=white)](https://www.python.org/downloads/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type: mypy](https://img.shields.io/badge/type%20checker-mypy-blue.svg)](https://mypy-lang.org/)

</div>

***

```python
import sqlseed

# Just one line. Auto-infers schema, auto-selects strategy, auto-optimizes writes.
result = sqlseed.fill("test.db", table="users", count=100_000)
print(result)
# → GenerationResult(table=users, count=100000, elapsed=2.34s, speed=42735 rows/s)
```

***

## 💡 Why sqlseed?

In development and testing workflows, we often need to populate SQLite databases with large volumes of realistic test data. Traditional approaches either require writing verbose data generation scripts or maintaining hard-to-scale SQL fixtures. sqlseed solves this with a declarative approach:

| Feature | sqlseed | Hand-written Scripts | SQL Fixtures |
| :------ | :-----: | :-----------------: | :----------: |
| Zero-config smart generation |    ✅    |         ❌         |      ❌      |
| Automatic FK maintenance |    ✅    |       Manual       |    Manual    |
| 100K+ rows | ✅ Streaming |    ⚠️ OOM    |      ❌      |
| Column semantic inference | ✅ 9-level strategy |    ❌    |      ❌      |
| Reproducible generation |  ✅ seed  |     ⚠️ Manual      |      ✅      |
| AI-powered tuning |  ✅ LLM  |         ❌         |      ❌      |
| Config reuse |  ✅ YAML  |         ❌         |      ❌      |

## ✨ Core Features

<table>
<tr>
<td width="50%">

**🚀 Zero-Config Smart Generation**

Auto-infers database schema and selects the best generator for each column via a 9-level strategy chain. Column named `email`? Generates email addresses. Column named `*_at`? Generates timestamps. No configuration needed.

</td>
<td width="50%">

**🎯 Declarative Fine-Grained Control**

Precisely control each column's data generation strategy, constraints, and null ratio via Python API or YAML/JSON configuration.

</td>
</tr>
<tr>
<td>

**🔗 Automatic FK Ordering**

Topological sort auto-detects table dependencies. SharedPool cross-table value sharing maintains referential integrity with zero configuration.

</td>
<td>

**🌊 Streaming Memory Safety**

`DataStream` yields batches via `Iterator[list[dict]]`. 1 million rows use the same memory as 1,000 rows.

</td>
</tr>
<tr>
<td>

**🧮 Expression Engine & Constraint Solving**

Supports derived column computation (`last_eight = card_number[-8:]`), unique constraint backtracking, and timeout protection against infinite loops.

</td>
<td>

**🤖 AI First-Class Citizen**

`sqlseed-ai` plugin uses LLM to analyze schema semantics, auto-generates YAML config suggestions with self-correction loop.

</td>
</tr>
<tr>
<td>

**🧩 11 Lifecycle Hooks**

pluggy-based plugin architecture covering every stage from provider registration to batch insertion.

</td>
<td>

**📊 3-Tier PRAGMA Optimization**

Intelligently switches between LIGHT / MODERATE / AGGRESSIVE write strategies based on data volume for maximum throughput.

</td>
</tr>
</table>

***

## 📦 Installation

### Basic

```bash
pip install sqlseed
```

### Choose Data Engine

```bash
# Recommended: Mimesis (high performance, great locale support)
pip install sqlseed[mimesis]

# Optional: Faker (rich ecosystem)
pip install sqlseed[faker]

# Install all
pip install sqlseed[all]
```

### Optional Plugins

```bash
# AI analysis plugin (requires openai SDK)
pip install sqlseed-ai

# MCP server (requires mcp SDK, lets AI assistants operate sqlseed)
pip install mcp-server-sqlseed

# MCP server + AI support (all-in-one)
pip install mcp-server-sqlseed[ai]
```

### Docs Build (Developers)

```bash
pip install sqlseed[docs]   # mkdocs-material + mkdocstrings
```

<details>
<summary><b>📋 Full Dev Environment Setup</b></summary>

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

</details>

***

## 🚀 Quick Start

### Get Started in 30 Seconds

Suppose you have a SQLite database `app.db` with a `users` table:

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    age INTEGER,
    phone TEXT,
    created_at TEXT,
    is_active INTEGER DEFAULT 1,
    balance REAL
);
```

One line of code fills 10,000 rows of high-quality test data:

```python
import sqlseed

result = sqlseed.fill("app.db", table="users", count=10_000)
print(result)
# → GenerationResult(table=users, count=10000, elapsed=0.52s, speed=19230 rows/s)
```

sqlseed automatically:

- ✅ Skips `id` (autoincrement PK)
- ✅ Skips `is_active` (has default value)
- ✅ `name` → generates real names
- ✅ `email` → generates email addresses
- ✅ `age` → generates integers 18–100
- ✅ `phone` → generates phone numbers
- ✅ `created_at` → generates datetime (matches `*_at` pattern)
- ✅ `balance` → generates floats

**Fully zero-config. Smart inference for everything.**

***

## 📖 Tutorials

### Tutorial 1: Python API — Fine-Grained Control

For precise control over each column, declare generation strategies via the `columns` parameter:

```python
import sqlseed

result = sqlseed.fill(
    "app.db",
    table="users",
    count=50_000,
    columns={
        # Shorthand: specify generator name directly
        "email": "email",
        "phone": "phone",

        # Full config: specify parameters
        "age": {"type": "integer", "min_value": 18, "max_value": 65},
        "balance": {"type": "float", "min_value": 0.0, "max_value": 100000.0, "precision": 2},
        "name": "name",

        # Random selection from candidate list
        "status": {"type": "choice", "choices": ["active", "inactive", "banned"]},
    },
    provider="mimesis",      # Use Mimesis engine
    locale="en_US",          # English locale
    seed=42,                 # Fixed seed for reproducibility
    clear_before=True,       # Clear table before generation
    enrich=True,             # Infer distribution from existing data
    transform="./transform_users.py",  # Custom transform per row
)
print(result)
```

#### Supported Generator Types

| Generator | Description | Example Parameters |
| :-------- | :---------- | :----------------- |
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

***

### Tutorial 2: Multi-Table Associations — Automatic FK Integrity

Use the context manager pattern to handle cross-table data dependencies:

```python
import sqlseed

with sqlseed.connect("app.db", provider="mimesis", locale="en_US") as db:
    # Step 1: Fill parent table first
    db.fill("users", count=10_000, seed=42)

    # Step 2: Fill child table — sqlseed auto-detects FK constraints
    #         and picks random values from users.id for orders.user_id
    db.fill("orders", count=50_000, columns={
        "amount": {"type": "float", "min_value": 9.99, "max_value": 999.99, "precision": 2},
        "quantity": {"type": "integer", "min_value": 1, "max_value": 20},
        "status": {"type": "choice", "choices": ["pending", "paid", "shipped", "delivered"]},
    })

    # Step 3: View generation report
    print(db.report())
    # → Database: app.db
    # → ==================================================
    # →   users: 10000 rows
    # →   orders: 50000 rows
```

> **💡 Tip**: If two tables share a column name (e.g., `account_id`), even without a declared FK constraint, sqlseed automatically maintains cross-table consistency via the **SharedPool implicit association mechanism**.

#### Explicit Cross-Table Associations (ColumnAssociation)

When the target column name differs from the source (e.g., `department_id` → `id`), or there's no FK constraint but you need an association, declare it explicitly via `associations`:

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
  - column_name: department_id     # Column name in the target table
    source_table: departments      # Source table providing values
    source_column: id              # Column name in source table (defaults to column_name)
    target_tables:                 # Target tables using this association
      - employees
    strategy: shared_pool          # Association strategy
```

This way, even without `FOREIGN KEY (department_id) REFERENCES departments(id)`, `department_id` values will come from `departments.id`.

***

### Tutorial 3: YAML Config-Driven Batch Generation

For complex multi-table scenarios, use YAML configuration:

**1. Generate config template**

```bash
sqlseed init generate.yaml --db app.db
```

**2. Edit config file**

```yaml
# generate.yaml
db_path: "app.db"
provider: mimesis
locale: en_US
optimize_pragma: true

tables:
  - name: users
    count: 100000
    clear_before: true
    seed: 42
    columns:
      - name: username
        generator: name
      - name: email
        generator: email
      - name: phone
        generator: phone
      - name: age
        generator: integer
        params:
          min_value: 18
          max_value: 65
      - name: status
        generator: choice
        params:
          choices: [0, 1, 2]
        null_ratio: 0.05       # 5% chance of NULL

  - name: orders
    count: 500000
    batch_size: 10000          # 10K rows per batch, optimizes memory
    columns:
      - name: user_id
        generator: foreign_key
        params:
          ref_table: users
          ref_column: id
          strategy: random
      - name: amount
        generator: float
        params:
          min_value: 1.0
          max_value: 9999.99
          precision: 2
      - name: created_at
        generator: datetime
        params:
          start_year: 2024
```

**3. Execute generation**

```bash
sqlseed fill --config generate.yaml
```

Or in Python:

```python
results = sqlseed.fill_from_config("generate.yaml")
for r in results:
    print(r)
```

***

### Tutorial 4: Derived Columns & Expression Engine

sqlseed v2.0 introduces column dependency DAG and expression engine for computing derived columns:

```yaml
# Bank card info table scenario
tables:
  - name: bank_cards
    count: 10000
    columns:
      - name: card_number
        generator: pattern
        params:
          regex: "62[0-9]{17}"     # 19-digit UnionPay card number
        constraints:
          unique: true

      - name: last_eight
        derive_from: card_number       # Depends on card_number
        expression: "value[-8:]"   # Last 8 digits
        constraints:
          unique: true

      - name: last_six
        derive_from: card_number
        expression: "value[-6:]"   # Last 6 digits

      - name: account_id
        generator: pattern
        params:
          regex: "U[0-9]{10}"
        constraints:
          unique: true
```

**How it works**:

1. sqlseed builds a column dependency DAG: `card_number → last_eight, last_six`
2. Topological sort determines generation order
3. Generates `card_number` first, then computes `last_eight` via `value[-8:]`
4. If `last_eight` unique constraint fails, backtracks to regenerate `card_number`

#### Expression Engine Functions (21 total)

| Function | Usage | Description |
| :------- | :---- | :---------- |
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
| Slicing | `value[-8:]` | Python slice syntax |
| Math | `value * 2 + 1` | Basic arithmetic |

> ⚠️ **Safety**: The expression engine is based on `simpleeval` with 5-second timeout protection. `import`, `exec`, and file I/O are not allowed.

***

### Tutorial 5: Transform Scripts — Complex Business Logic

For complex business logic that can't be expressed declaratively, write Python transform scripts:

**1. Write transform script**

```python
# transform_users.py
def transform_row(row, ctx):
    """Called for every generated row."""

    # Calculate VIP level based on age
    age = row.get("age", 0)
    if age >= 60:
        row["vip_level"] = 3
    elif age >= 40:
        row["vip_level"] = 2
    else:
        row["vip_level"] = 1

    # Normalize phone format
    phone = row.get("phone", "")
    if phone and not phone.startswith("+1"):
        row["phone"] = f"+1{phone}"

    return row
```

**2. Use in CLI**

```bash
sqlseed fill app.db --table users --count 10000 --transform transform_users.py
```

**3. Use in YAML**

```yaml
tables:
  - name: users
    count: 10000
    transform: "./transform_users.py"
```

***

### Tutorial 6: Preview & Debug

Preview data before generating at scale:

**Python API:**

```python
rows = sqlseed.preview("app.db", table="users", count=5, seed=42)
# Also supports enrich and transform parameters
rows = sqlseed.preview("app.db", table="users", count=5, seed=42, enrich=True)
for row in rows:
    print(row)
# → {'name': 'John Smith', 'email': 'jsmith@example.com', 'age': 32, ...}
# → {'name': 'Jane Doe', 'email': 'jdoe@test.org', 'age': 28, ...}
# → ...
```

**CLI (Rich table output):**

```bash
sqlseed preview app.db --table users --count 5

# ┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
# ┃ name       ┃ email                ┃ age ┃ created_at          ┃
# ┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
# │ John Smith │ jsmith@example.com   │ 32  │ 2024-03-15 08:23:11 │
# │ ...        │ ...                  │ ... │ ...                 │
# └────────────┴──────────────────────┴─────┴─────────────────────┘
```

**View column mapping strategy:**

```bash
sqlseed inspect app.db --table users --show-mapping

# See what generation strategy sqlseed chose for each column
# ┏━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
# ┃ Column     ┃ Type    ┃ Nullable ┃ Generator    ┃ Params       ┃
# ┡━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
# │ id         │ INTEGER │ ✗        │ skip         │ {}           │
# │ name       │ TEXT    │ ✗        │ name         │ {}           │
# │ email      │ TEXT    │ ✓        │ email        │ {}           │
# │ age        │ INTEGER │ ✓        │ integer      │ {min: 18...} │
# │ ...        │ ...     │ ...      │ ...          │ ...          │
# └────────────┴─────────┴──────────┴──────────────┴──────────────┘
```

***

### Tutorial 7: Snapshots & Replay

Save a successful generation config for exact replay later:

```bash
# Generate and save snapshot
sqlseed fill app.db --table users --count 10000 --seed 42 --snapshot
# → Snapshot saved: snapshots/2026-04-15_033000_users.yaml

# Replay anytime
sqlseed replay snapshots/2026-04-15_033000_users.yaml
# → GenerationResult(table=users, count=10000, elapsed=0.52s, speed=19230 rows/s)
```

Use cases:

- 🧪 Reproducible test data in CI/CD
- 📋 Consistent test environments across teams
- 🔄 Quick database state reconstruction during development

***

### Tutorial 8: AI-Powered Configuration (sqlseed-ai Plugin)

Let LLM analyze your database schema and auto-generate optimal config suggestions:

```bash
# Install AI plugin
pip install sqlseed-ai

# Set API key
export SQLSEED_AI_API_KEY="your-api-key"
export SQLSEED_AI_BASE_URL="https://your-llm-api-endpoint"

# AI analysis and config generation
sqlseed ai-suggest app.db --table bank_cards --output bank_cards.yaml

# AI suggestions with self-correction (3 rounds by default)
sqlseed ai-suggest app.db --table bank_cards --output bank_cards.yaml --verify

# Specify model (defaults to most popular free model)
sqlseed ai-suggest app.db --table bank_cards --output bank_cards.yaml --model nvidia/nemotron-3-super-120b-a12b:free

# Skip cache
sqlseed ai-suggest app.db --table bank_cards --output bank_cards.yaml --no-cache
```

**AI Workflow**:

```
1. Extract schema context (columns, indexes, sample data, FK, distribution)
2. Build LLM prompt with few-shot examples
3. LLM returns JSON column config suggestions
4. AiConfigRefiner auto-validates config correctness
5. If errors found (unknown generator, type mismatch, etc.), sends correction request to LLM
6. Up to 3 self-correction rounds, outputs validated YAML config
```

> **💡 Environment Variables**: Supports `SQLSEED_AI_API_KEY`, `SQLSEED_AI_BASE_URL`, `SQLSEED_AI_MODEL`. Also supports `OPENAI_API_KEY` / `OPENAI_BASE_URL` as fallback. Defaults to auto-selecting the most popular free model from OpenRouter (base_url `https://openrouter.ai/api/v1`). Set `--model` or `SQLSEED_AI_MODEL` to specify a model.

***

### Tutorial 9: MCP Server Integration

Let AI assistants (Claude, Cursor, etc.) operate sqlseed directly via [Model Context Protocol](https://modelcontextprotocol.io/):

```bash
# Install MCP server
pip install mcp-server-sqlseed

# All-in-one: MCP server + AI support
pip install mcp-server-sqlseed[ai]

# Manual start (usually managed by MCP client)
python -m mcp_server_sqlseed
```

**Configure MCP client** (Claude Desktop example):

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    }
  }
}
```

**MCP Capabilities**:

| Type | Name | Description |
| :--- | :--- | :---------- |
| 📖 Resource | `sqlseed://schema/{db_path}/{table_name}` | Get table schema as JSON |
| 🔍 Tool | `sqlseed_inspect_schema` | Inspect schema (columns, FK, indexes, samples, schema_hash) |
| 🤖 Tool | `sqlseed_generate_yaml` | AI-driven YAML config generation with self-correction. Supports `api_key`/`base_url`/`model` overrides |
| ⚡ Tool | `sqlseed_execute_fill` | Execute data generation (supports YAML config string, includes `enrich` option) |

This means you can tell your AI assistant:

> "Analyze the structure of the `bank_cards` table in `app.db`, generate a YAML config, then fill 5000 rows."

The AI assistant will call `sqlseed_inspect_schema` → `sqlseed_generate_yaml` → `sqlseed_execute_fill` in sequence, without you writing any code.

***

### Tutorial 10: Custom Provider Plugin

You can create your own data generation provider:

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

    # ... handle generator names you want to support
    # Full Protocol: src/sqlseed/generators/_protocol.py
```

To reuse the built-in generator name dispatch logic instead of hand-writing `generate()` routing, inherit `BaseProvider` and override selectively.

**Registration method 1: via `pyproject.toml` entry-point (recommended)**

```toml
[project.entry-points."sqlseed"]
my_custom = "my_provider:MyCustomProvider"
```

**Registration method 2: via plugin hook**

```python
from sqlseed.plugins.hookspecs import hookimpl

class MyPlugin:
    @hookimpl
    def sqlseed_register_providers(self, registry):
        from my_provider import MyCustomProvider
        registry.register(MyCustomProvider())
```

***

## 🖥️ CLI Quick Reference

```bash
# ═══════════════════════════════════════
# 📋 Data Generation
# ═══════════════════════════════════════

# Fill data (--count required when not using --config)
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

# Enable debug logging
SQLSEED_LOG_LEVEL=DEBUG sqlseed fill app.db -t users -n 10

# ═══════════════════════════════════════
# 🔍 Inspect & Preview
# ═══════════════════════════════════════

# Preview data (no write)
sqlseed preview app.db --table users --count 5

# List all tables
sqlseed inspect app.db

# View column mapping strategy
sqlseed inspect app.db --table users --show-mapping

# ═══════════════════════════════════════
# 📸 Snapshots & Replay
# ═══════════════════════════════════════

# Generate config template
sqlseed init generate.yaml --db app.db

# Replay snapshot
sqlseed replay snapshots/2026-04-15_users.yaml

# ═══════════════════════════════════════
# 🤖 AI Features
# ═══════════════════════════════════════

# AI suggestions (requires sqlseed-ai)
sqlseed ai-suggest app.db -t users -o users.yaml
sqlseed ai-suggest app.db -t users -o users.yaml --verify

# Specify API config
sqlseed ai-suggest app.db -t users -o users.yaml --api-key sk-xxx --base-url https://api.openai.com/v1

# Control self-correction
sqlseed ai-suggest app.db -t users -o users.yaml --max-retries 0   # Disable
sqlseed ai-suggest app.db -t users -o users.yaml --no-verify       # Skip verification

# Skip cache
sqlseed ai-suggest app.db -t users -o users.yaml --no-cache
```

***

## 🧠 9-Level Smart Column Mapping

One of sqlseed's core highlights is the `ColumnMapper`'s 9-level strategy chain. Each column is matched by priority:

```
Level 1 │ Autoincrement PK    PK + AUTOINCREMENT / INTEGER → skip
        ▼
Level 2 │ User config         columns={"email": "email"} highest priority
        ▼
Level 3 │ Custom exact match  Rules registered via plugin hooks
        ▼
Level 4 │ Built-in exact      74 rules: email→email, phone→phone, age→integer...
        ▼
Level 5 │ DEFAULT check       Has default → skip / __enrich__ (when enrich=True)
        ▼
Level 6 │ Custom pattern      Regex rules registered via plugin hooks
        ▼
Level 7 │ Built-in pattern    25 regexes: *_at→datetime, *_id→foreign_key, is_*→boolean...
        ▼
Level 8 │ NULLABLE fallback   Nullable → skip / __enrich__
        ▼
Level 9 │ Type-faithful       VARCHAR(32)→max 32 chars, INT8→0~255, BLOB(1024)→1024 bytes
```

What this means:

- Column `user_email` → Level 7 pattern `*_email` → `email` generator ✅
- Column `is_verified` → Level 7 pattern `is_*` → `boolean` generator ✅
- Column type `VARCHAR(20)` → Level 9 type fallback → max 20-char string ✅
- Column with `DEFAULT 1` → Level 5 → skip generation ✅
- Column `gender` with `DEFAULT 'male'` → Level 4 exact match → `choice` generator (exact match takes priority over DEFAULT) ✅

***

## 🧩 Plugin System

sqlseed provides 11 hook points via [pluggy](https://pluggy.readthedocs.io/), covering the full data generation lifecycle:

| Hook | firstresult | Trigger |
| :--- | :---------: | :------ |
| `sqlseed_register_providers` |    <br />   | Register custom data providers |
| `sqlseed_register_column_mappers` |    <br />   | Register custom column mapping rules |
| `sqlseed_ai_analyze_table` |      ✓      | AI analyzes table schema (returns column config) |
| `sqlseed_pre_generate_templates` |      ✓      | AI pre-computes candidate value pools |
| `sqlseed_before_generate` |    <br />   | Before data generation loop |
| `sqlseed_after_generate` |    <br />   | After data generation completes |
| `sqlseed_transform_row` |    <br />   | Per-row transform (hot path, mind performance) |
| `sqlseed_transform_batch` |    <br />   | Per-batch transform (supports chaining) |
| `sqlseed_before_insert` |    <br />   | Before each batch write to DB |
| `sqlseed_after_insert` |    <br />   | After each batch write to DB |
| `sqlseed_shared_pool_loaded` |    <br />   | After SharedPool registration (pool readable) |

***

## 🏗️ Project Architecture

```
src/sqlseed/
├── __init__.py              # Public API (fill, connect, fill_from_config, preview)
├── core/                    # ===== Core Orchestration =====
│   ├── orchestrator.py      # DataOrchestrator main engine
│   ├── mapper.py            # ColumnMapper 9-level strategy chain
│   ├── schema.py            # SchemaInferrer — columns, indexes, distribution
│   ├── relation.py          # RelationResolver + SharedPool — FK & cross-table sharing
│   ├── column_dag.py        # ColumnDAG — column dependency graph + topological sort
│   ├── expression.py        # ExpressionEngine — safe expressions (simpleeval + timeout)
│   ├── constraints.py       # ConstraintSolver — unique backtracking
│   ├── transform.py         # TransformLoader — dynamic user script loading
│   └── result.py            # GenerationResult dataclass
├── generators/              # ===== Generator Layer =====
│   ├── _protocol.py         # DataProvider Protocol + UnknownGeneratorError
│   ├── registry.py          # ProviderRegistry (entry-point auto-discovery)
│   ├── base_provider.py     # Built-in base generators (zero dependencies)
│   ├── faker_provider.py    # Faker adapter
│   ├── mimesis_provider.py  # Mimesis adapter
│   └── stream.py            # DataStream streaming + constraint backtracking
├── database/                # ===== Database Layer =====
│   ├── _protocol.py         # DatabaseAdapter Protocol (ColumnInfo, ForeignKeyInfo, IndexInfo)
│   ├── sqlite_utils_adapter.py   # Default adapter
│   ├── raw_sqlite_adapter.py     # sqlite3 fallback adapter
│   └── optimizer.py         # PragmaOptimizer 3-tier optimization
├── plugins/                 # ===== Plugin Layer =====
│   ├── hookspecs.py         # 11 pluggy hook definitions
│   └── manager.py           # PluginManager
├── config/                  # ===== Config Management =====
│   ├── models.py            # Pydantic models (GeneratorConfig/TableConfig/ColumnConfig)
│   ├── loader.py            # YAML/JSON load & save
│   └── snapshot.py          # Snapshot save & replay
├── cli/                     # ===== CLI =====
│   └── main.py              # click commands (fill/preview/inspect/init/replay/ai-suggest)
└── _utils/                  # ===== Internal Utilities =====
    ├── sql_safe.py          # quote_identifier — SQL injection protection
    ├── schema_helpers.py    # AUTOINCREMENT detection
    ├── metrics.py           # MetricsCollector performance metrics
    ├── progress.py          # Rich progress bar
    └── logger.py            # structlog logging

plugins/
├── sqlseed-ai/              # AI plugin — LLM-driven smart configuration
│   └── src/sqlseed_ai/      # SchemaAnalyzer, AiConfigRefiner, few-shot examples...
└── mcp-server-sqlseed/      # MCP server — AI assistant integration
    └── src/mcp_server_sqlseed/   # FastMCP tools (sqlseed_inspect_schema/sqlseed_generate_yaml/sqlseed_execute_fill)
```

***

## 🛠️ Development

```bash
# Run tests (with coverage)
pytest

# Lint
ruff check src/ tests/

# Auto-fix
ruff check --fix src/ tests/

# Type check
mypy src/sqlseed/
```

Tests cover all core modules, with path structure mirroring `src/`: `test_core/`, `test_database/`, `test_generators/`, `test_plugins/`, `test_config/`, `test_utils/`.

### Dependencies

| Package | Core Dependencies | Description |
| :------ | :---------------- | :---------- |
| `sqlseed` | sqlite-utils, pydantic, pluggy, structlog, pyyaml, click, rich, typing_extensions, simpleeval, **rstr** | rstr used for `pattern` generator regex matching |
| `sqlseed[faker]` | + faker>=30.0 | Faker data engine |
| `sqlseed[mimesis]` | + mimesis>=18.0 | Mimesis data engine (recommended) |
| `sqlseed[docs]` | + mkdocs-material, mkdocstrings | Documentation build |
| `sqlseed-ai` | sqlseed, **openai>=1.0** | AI plugin, auto-registered via entry-point |
| `mcp-server-sqlseed` | sqlseed, **mcp>=1.0** | MCP server, standalone CLI tool |
| `mcp-server-sqlseed[ai]` | + sqlseed-ai | MCP server with AI support |

***

## 📄 License

[AGPL-3.0-or-later](LICENSE)

***

<div align="center">

**🌱 sqlseed** — *Stop writing fixtures. Start generating data.*

</div>
