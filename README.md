<div align="center">

# 🌱 sqlseed

**[English](README.md)** | [中文](README.zh-CN.md)

### Declarative Multi-Database Test Data Generation Toolkit

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

In development and testing workflows, we often need to populate SQLite and PostgreSQL databases with large volumes of realistic test data. Traditional approaches either require writing verbose data generation scripts or maintaining hard-to-scale SQL fixtures. sqlseed solves this with a declarative approach:

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

Supports derived column computation (`short_code = project_no[-8:]`), unique constraint backtracking, and timeout protection against infinite loops.

</td>
<td>

**🤖 AI First-Class Citizen**

`sqlseed-ai` plugin uses LLM to analyze schema semantics, auto-generates YAML config suggestions with self-correction loop.

</td>
</tr>
<tr>
<td>

**🧩 12 Lifecycle Hooks**

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

# Note: Faker is a required core dependency, included in `pip install sqlseed`.

# Install all
pip install sqlseed[all]
```

### Choose Database Backend

sqlseed supports SQLite (default) and PostgreSQL via SQLAlchemy.

```bash
# PostgreSQL support (psycopg driver)
pip install "sqlseed[postgres]"

# All database backends + all data engines
pip install "sqlseed[all]"
```

> **💡 Note**: SQLite works out of the box with no extra dependencies. PostgreSQL driver is only required when connecting to that database.

### Optional Plugins

```bash
# AI analysis plugin (requires openai SDK)
pip install sqlseed-ai

# MCP server (requires mcp SDK, lets AI assistants operate sqlseed)
pip install mcp-server-sqlseed

# AI MCP server (4 LLM tools, requires sqlseed-ai)
pip install "sqlseed-ai[mcp]"
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

### Interactive Quickstart

```bash
python scripts/quickstart.py
```

### Try with Demo Database

Want to try sqlseed right away? Build the demo database:

```bash
python examples/build_demo_db.py
```

Then explore:

```bash
sqlseed preview examples/sqlseed_demo.db --table members --count 5
sqlseed inspect examples/sqlseed_demo.db --show-mapping
sqlseed fill examples/sqlseed_demo.db --table members --count 100
```

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

### Connect to PostgreSQL

sqlseed supports PostgreSQL in addition to SQLite. Pass a SQLAlchemy URL instead of a file path:

```python
import sqlseed

# PostgreSQL (requires: pip install "sqlseed[postgres]")
result = sqlseed.fill(
    "postgresql+psycopg://user:password@localhost:5432/mydb",
    table="users",
    count=10_000,
)
print(result)
```

The same API works for both databases — schema inference, FK resolution, expression engine, and plugin hooks all run identically across SQLite and PostgreSQL.

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
| `word` | Real English word | — |
| `catch_phrase` | Business catch phrase (multi-word) | — |
| `password` | Password | `length` |
| `choice` | Pick from list | `choices` |
| `weighted_choice` | Weighted random pick | `choices` (list of `{value, weight}`) or `weighted_choices` (dict) |
| `json` | JSON string | `schema` |
| `pattern` | Regex match | `regex` |
| `template` | Formatted string with placeholders | `template`, `sequence_start`, `sequence_step` |
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

> **💡 Tip**: If two tables share a column name (e.g., `member_no`), even without a declared FK constraint, sqlseed automatically maintains cross-table consistency via the **SharedPool implicit association mechanism**.

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
# Project info table scenario
tables:
  - name: projects
    count: 10000
    columns:
      - name: project_no
        generator: pattern
        params:
          regex: "PRJ-\\d{6}"       # Project number pattern
        constraints:
          unique: true

      - name: short_code
        derive_from: project_no       # Depends on project_no
        expression: "value[-6:]"   # Last 6 chars
        constraints:
          unique: true

      - name: region_code
        derive_from: project_no
        expression: "value[-4:]"   # Last 4 chars

      - name: member_no
        generator: pattern
        params:
          regex: "M-\\d{4}"         # Member number pattern
        constraints:
          unique: true
```

**How it works**:

1. sqlseed builds a column dependency DAG: `project_no → short_code, region_code`
2. Topological sort determines generation order
3. Generates `project_no` first, then computes `short_code` via `value[-6:]`
4. If `short_code` unique constraint fails, backtracks to regenerate `project_no`

#### Expression Engine Functions (26 total)

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
| `timedelta(days, seconds)` | `value + timedelta(days=7)` | Date/time arithmetic (adds interval to date source) |
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
# → Snapshot saved: <cache_dir>/snapshots/YYYY-MM-DD_HHMMSS_users.yaml

# Replay anytime
sqlseed replay <cache_dir>/snapshots/YYYY-MM-DD_HHMMSS_users.yaml
# → GenerationResult(table=users, count=10000, elapsed=0.52s, speed=19230 rows/s)
```

Use cases:

- 🧪 Reproducible test data in CI/CD
- 📋 Consistent test environments across teams
- 🔄 Quick database state reconstruction during development

***

### Tutorial 8: AI-Powered Configuration (sqlseed-ai Plugin)

Let LLM analyze your database schema and auto-generate optimal config suggestions. The sqlseed-ai plugin provides **3 CLI commands**:

| Command | Purpose | When to Use |
| :------ | :------ | :---------- |
| `ai-suggest` | Per-table LLM analysis with self-correction | Single-table analysis with `--verify` validation |
| `ai-analyze` | Full/partial DB analysis via v4 AutoHealOrchestrator (default) | Multi-table YAML generation with contract-driven self-healing |
| `auto-heal` | Repair broken YAML configs via LLM + rule-based pipeline | Fix YAML files that fail `sqlseed fill` |

```bash
# Install AI plugin
pip install sqlseed-ai

# Set API key
export SQLSEED_AI_API_KEY="your-api-key"

# ─────────────────────────────────────────────
# ai-suggest: Per-table LLM analysis
# ─────────────────────────────────────────────

# AI analysis and config generation for a single table
sqlseed ai-suggest app.db --table projects --output projects.yaml

# AI suggestions with self-correction (3 rounds by default)
sqlseed ai-suggest app.db --table projects --output projects.yaml --verify

# Specify model (defaults to Gemma 4 26B via Google AI Studio)
sqlseed ai-suggest app.db --table projects --output projects.yaml --model gemma-4-26b-a4b-it

# Use local LM Studio / Ollama
sqlseed ai-suggest app.db --table projects --output projects.yaml --backend lm_studio --model google/gemma-4-e4b

# ─────────────────────────────────────────────
# ai-analyze: Full DB analysis via v4 architecture (default)
# ─────────────────────────────────────────────

# Analyze entire database and generate YAML (v4 AutoHealOrchestrator)
sqlseed ai-analyze --db app.db -o config.yaml

# Output to stdout (no -o)
sqlseed ai-analyze --db app.db

# Multi-DB via --url
sqlseed ai-analyze --url "postgresql+psycopg://user:pass@host/db" -o config.yaml

# Log full LLM interactions for debugging
sqlseed ai-analyze --db app.db -o config.yaml --log-llm

# ─────────────────────────────────────────────
# auto-heal: Repair broken YAML configs
# ─────────────────────────────────────────────

# After ai-analyze, if `sqlseed fill` fails on some tables, repair the YAML
sqlseed auto-heal --db app.db --config broken.yaml -o healed.yaml

# Use a different LLM model for healing
sqlseed auto-heal --db app.db --config broken.yaml -o healed.yaml --model gemma-4-26b-a4b-it
```

**Gemma 4 Native Function Calling (GEMMA_TOOLS)**:

sqlseed-ai supports Gemma 4 model family (2B/4B/12B/26B/31B) with Native Function Calling via GEMMA_TOOLS protocol. Supported backends:

| Backend | Description | Configuration |
| :------ | :---------- | :------------ |
| **Google AI Studio** | Official API, recommended for Gemma 4 26B/31B | `--backend google_ai_studio` or `SQLSEED_AI_BACKEND=google_ai_studio` |
| **LM Studio** | Local inference, suitable for Gemma 4 2B/4B | `--backend lm_studio` or `SQLSEED_AI_BACKEND=lm_studio` |
| **Ollama** | Local inference, suitable for Gemma 4 2B/4B/26B | `--backend ollama` or `SQLSEED_AI_BACKEND=ollama` |
| **OpenAI-compatible** | Generic OpenAI-compatible endpoint (e.g., OpenRouter, DeepSeek) | `--backend openai_compat` or `SQLSEED_AI_BACKEND=openai_compat` |

> **💡 OpenRouter (Free)**: For users without a paid API key, OpenRouter provides free models. Set `SQLSEED_AI_BACKEND=openai_compat`, `SQLSEED_AI_BASE_URL=https://openrouter.ai/api/v1`, and `SQLSEED_AI_MODEL=<free-model-name>`.

```bash
# Skip cache
sqlseed ai-suggest app.db --table projects --output projects.yaml --no-cache
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

**v4 Contract-Driven Self-Healing Architecture** (used by `ai-analyze` and `auto-heal`):

```
Layer 1: contracts/    Sparse contract matrix + resolver (closed set of known-bad combos)
Layer 2: validator/    FastValidator (single-column + cross-column + dialect error parsing)
Layer 3: repair/       Stateless repair strategies (REPAIR_STRATEGIES dict, open for extension)
Layer 4: healer/       LLM healer + oscillation detection + progressive degrade + cascade
Layer 5: auto_heal/    AutoHealOrchestrator — top-level entry (SchemaSnapshot → SubgraphSplitter → per-subgraph validate/repair/heal → BrokenEdgeAligner → emit YAML)
Layer 6: analyzer/     LLM table-level analysis (streaming + tool-calling, protocol-based)
```

The `_build_subgraph_config()` method in `AutoHealOrchestrator` performs deterministic CHECK-constraint inference before any LLM call: `_parse_single_column_check()` handles LENGTH()/IN/BETWEEN/range patterns (including mixed `> AND <=` and `>= AND <`, `col != 0` non-zero constraint, plus float exclusive bounds `col > X` / `col < Y` / `col > X AND col <= Y` / `col > X AND col < Y` / `col >= X AND col < Y` with 0.01 epsilon to avoid generating the boundary value, plus `col IS NULL OR <inner_expr>` prefix stripping that peels off the optional NULL branch before parsing the inner expression with the existing patterns), while `_infer_cross_column_config()` handles 62 cross-column patterns (col >= other, col > other, col <= other, col < other, col != other, col >= col1 * col2, col >= col2 * CONSTANT [Pattern 7b, column-times-literal-constant lower bound — derive_from col2, expression `value * CONSTANT`], col = col1 (+|-|*) col2, col = col1 + col2 + col3, col = abs(col1) (+|-|*) col2, col = col1 (+|-|*) abs(col2), col = abs(col1) * abs(col2), col = abs(col1), col IS NULL OR col (>=|>|<=|<) other [Pattern 1, all 4 operators + date/float/int types], col IS NULL OR other IS NULL OR col (>=|>|<=|<) other [Pattern 1b, 3-way OR with NULL escape for both columns — None-guard expression prevents TypeError when source col is None], col >= X AND col <= other_col, col >= other_col AND col <= Y, col > X AND col < other_col, col > other_col AND col < Y, col != VALUE OR other_col = VALUE2, col1 + col2 = col reverse-sum, col = VALUE OR other_col < col2 OR other_col > col3 range-membership, col = (col1 + col2 [+ col3]) / N average [Pattern 21, int() wrapped for INTEGER columns to match SQLite integer-division CHECK semantics], col <= col2 * CONSTANT percentage upper bound [Pattern 22], col >= col2 * CONST1 AND col <= col2 * CONST2 [Pattern 22c, dual multiplier bounds across two CHECKs — cross-constraint scan before per-constraint loop; derive_from col2, expression `value * random_float(CONST1, CONST2)`], col = VALUE OR col1 < X OR col2 < X [OR col3 < X] multi-column threshold [Pattern 23, val/opposite swapped to satisfy both OR-form and AND-form dual CHECKs], col = VALUE OR col (>|>=|<|<=) other_col [Pattern 24, conditional comparison — 50% VALUE, 50% satisfying the inequality], col1 != VALUE OR col (>|>=|<|<=) other_col [Pattern 24b, inequality-first variant of Pattern 24 — derive_from other_col, comparison-satisfying value when cond_col == VALUE, else 50% compliant/50% safe zero; cross-constraint cap: when col <= other_col also exists, uses exact equality `value` to satisfy both >= and <=], col = col1 * col2 + col3 [Pattern 25, multiplication + addition chain], col = VALUE OR other_col IN ('a','b','c') [Pattern 26, conditional enum — col set to non-VALUE when other_col is in the set], col1 != VALUE OR col IN ('a','b','c') [Pattern 26b, inequality-first variant of Pattern 26 — derive_from cond_col, random set value when cond_col == VALUE, else first set value], col1 != VALUE OR col = 'V1' OR col = 'V2' [Pattern 26c, explicit OR-equality variant of Pattern 26b — handles `col = 'V1' OR col = 'V2'` syntax instead of IN()], other_col = 'V1' AND col OP1 X1 OR other_col = 'V2' AND col OP2 X2 [OR ...] [Pattern 27, N-way conditional range — nested ternary picks per-clause random range], other_col != VALUE OR col > 0 [Pattern 28, conditional requirement — col set to positive random when other_col == VALUE, else 0], col1 != INTEGER_VALUE OR col > X [Pattern 28b, integer-value variant of Pattern 28 — derive_from col1, positive random when col1 == INT_VALUE, else 0], col = col1 (+|-) col2 (+|-) col3 [Pattern 29, three-column mixed arithmetic chain — derive_from col1, reference col2/col3 via row dict], col1 != VALUE OR col IS NULL [Pattern 30, conditional NULL — FK columns return None for BOTH branches to avoid FK violations; non-FK columns return 0/0.0], col1 = VALUE OR col IS NOT NULL [Pattern 30b, reverse of Pattern 30 — when col1 != VALUE, col must be non-NULL; FK columns use 1 (first autoincrement id), non-FK columns use 0/0.0], col1 != VALUE OR col = VALUE2 [Pattern 31, conditional equality — col set to VALUE2 when col1 == VALUE, else safe random], col >= X AND col <= col2 * CONSTANT [Pattern 22b, compound range with multiplier upper bound — derive_from col2, max(X, value * factor)], (col1 = VALUE AND col > X) OR (col1 IN (...) AND col IS NULL) [Pattern 32, conditional value/NULL — col positive random when col1 == VALUE, NULL when col1 in other set], (col1 IN (...) AND col = col2 + col3) OR (col1 IN (...) AND col = col2 - col3) [Pattern 33, conditional arithmetic by type — derive_from col2, op selected by col1's type set], col1 != VALUE OR col2 (<|<=) X [Pattern 34, conditional upper bound — max_value set to X or X-epsilon; min_value preserved from single-column CHECK via _infer_from_check_constraints merge], col1 != INTEGER_VALUE OR col (<|<=) X [Pattern 34b, integer-value variant of Pattern 34 — same max_value logic, accepts unquoted integer VALUE], col1 IN (...) OR col IS NULL [Pattern 35, conditional NULL with IN set — date columns get null_ratio=1.0; non-date columns get derive_from with None for non-matching values], other_col = 'V1' AND col (>=|>) X1 AND col (<|<=) Y1 OR other_col = 'V2' AND col (>=|>) X2 AND col (<|<=) Y2 [OR ...] [Pattern 36, N-way conditional range with dual bounds — each clause has both a lower and upper literal bound; nested ternary picks per-clause random_int/random_float range], multiple `col1 != VALUE_i OR col OP_i X_i` on same column [Pattern 37, multi-conditional cross-column — when 2+ separate CHECK constraints constrain the SAME target column based on the SAME enum column's value; derive_from col1, nested ternary with a branch per VALUE_i, default branch for unmatched enum values], col = (col1 + col2) * (CONST - col3) [Pattern 38, complex arithmetic — derive_from col1, expression `(value + row['col2']) * (CONST - row['col3'])`], col1 IS NULL OR col <= col2 + col3 [Pattern 39, compound addition upper bound — derive_from col2, None-guard when value is None, else `(value + row['col3']) * random_float(0.0, 1.0)`]).

> **💡 Environment Variables**: Supports `SQLSEED_AI_API_KEY`, `SQLSEED_AI_BASE_URL`, `SQLSEED_AI_MODEL`, `SQLSEED_AI_BACKEND`. Also supports `OPENAI_API_KEY` / `OPENAI_BASE_URL` as fallback. Defaults to Gemma 4 26B via Google AI Studio. Supported backends: `google_ai_studio`, `lm_studio`, `ollama`, `openai_compat`.

***

### Tutorial 9: MCP Server Integration

Let AI assistants (Claude, Cursor, etc.) operate sqlseed directly via [Model Context Protocol](https://modelcontextprotocol.io/):

```bash
# Install MCP server (core, no LLM dependency)
pip install mcp-server-sqlseed

# Install AI MCP server (LLM-driven, requires sqlseed-ai)
pip install "sqlseed-ai[mcp]"

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

**mcp-server-sqlseed** (2 Tools, 0 Resources — core, no LLM dependency):

| Type | Name | Description |
| :--- | :--- | :---------- |
| 🤖 Tool | `sqlseed_generate_yaml` | Rule-driven YAML config generation via `ColumnMapper` |
| ⚡ Tool | `sqlseed_execute_fill` | Execute data generation (supports YAML config string, includes `enrich` option) |

**sqlseed-ai[mcp]** (4 Tools, 0 Resources — LLM-driven, install with `pip install "sqlseed-ai[mcp]"`):

| Type | Name | Description |
| :--- | :--- | :---------- |
| 🧠 Tool | `sqlseed_ai_generate_yaml` | AI-driven YAML config generation with self-correction |
| 🧠 Tool | `sqlseed_gemma4_analyze` | Analyze schema using Gemma 4 with Native Function Calling |
| 🧠 Tool | `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow (analyze -> config -> fill) |
| 🧠 Tool | `sqlseed_list_gemma_models` | List available Gemma 4 models and backend status |

This means you can tell your AI assistant:

> "Analyze the structure of the `projects` table in `app.db`, generate a YAML config, then fill 5000 rows."

The AI assistant will call `sqlseed_generate_yaml` → `sqlseed_execute_fill` in sequence, without you writing any code.

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
sqlseed replay <cache_dir>/snapshots/YYYY-MM-DD_users.yaml

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

# Full DB analysis via v4 AutoHealOrchestrator (default path)
sqlseed ai-analyze --db app.db -o config.yaml
sqlseed ai-analyze --url "postgresql+psycopg://user:pass@host/db" -o config.yaml

# Repair broken YAML configs after a failed `sqlseed fill`
sqlseed auto-heal --db app.db --config broken.yaml -o healed.yaml
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
Level 4 │ Built-in exact      <!-- BEGIN:AUTO-GENERATED:exact-match-rule-count -->75<!-- END:AUTO-GENERATED:exact-match-rule-count --> rules: email→email, phone→phone, age→integer...
        ▼
Level 5 │ DEFAULT check       Has default → skip / __enrich__ (when enrich=True)
        ▼
Level 6 │ Custom pattern      Regex rules registered via plugin hooks
        ▼
Level 7 │ Built-in pattern    <!-- BEGIN:AUTO-GENERATED:pattern-match-rule-count -->29<!-- END:AUTO-GENERATED:pattern-match-rule-count --> regexes: *_at→datetime, *_id→foreign_key, is_*→boolean...
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

sqlseed provides 12 hook points via [pluggy](https://pluggy.readthedocs.io/), covering the full data generation lifecycle:

| Hook | firstresult | Trigger |
| :--- | :---------: | :------ |
| `sqlseed_register_providers` |    <br />   | Register custom data providers |
| `sqlseed_register_column_mappers` |    <br />   | Register custom column mapping rules |
| `sqlseed_ai_analyze_table` |      ✓      | AI analyzes table schema (returns column config) |
| `sqlseed_apply_ai_suggestions` |      ✓      | High-level AI mediation (orchestrator entry; implemented in `sqlseed_ai.ai_mediator`) |
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
│   ├── orchestrator/        # DataOrchestrator package (4 mixins + 1 shared data module)
│   │   ├── __init__.py
│   │   ├── _common.py
│   │   ├── _connection.py
│   │   ├── _specs.py
│   │   ├── _generation.py
│   │   └── _query.py
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
│   ├── sqlalchemy_adapter.py    # Default adapter (SQLite/PostgreSQL)
│   ├── raw_sqlite_adapter.py     # sqlite3 fallback adapter
│   └── optimizer.py         # PragmaOptimizer 3-tier optimization
├── plugins/                 # ===== Plugin Layer =====
│   ├── hookspecs.py         # 12 pluggy hook definitions
│   └── manager.py           # PluginManager
├── config/                  # ===== Config Management =====
│   ├── models.py            # Pydantic models (GeneratorConfig/TableConfig/ColumnConfig)
│   ├── loader.py            # YAML/JSON load & save
│   └── snapshot.py          # Snapshot save & load
└── _utils/                  # ===== Internal Utilities =====
    ├── sql_safe.py          # quote_identifier — SQL injection protection
    ├── schema_helpers.py    # AUTOINCREMENT detection
    ├── metrics.py           # MetricsCollector performance metrics
    ├── paths.py             # get_cache_dir — platform cache directory
    ├── progress.py          # Rich progress bar
    └── logger.py            # structlog logging

plugins/
├── sqlseed-cli/             # CLI plugin — click commands (fill/preview/inspect/init/replay)
│   └── src/sqlseed_cli/     # Standalone package, separate pyproject.toml
├── sqlseed-ai/              # AI plugin — LLM-driven smart configuration
│   └── src/sqlseed_ai/      # SchemaAnalyzer, AiConfigRefiner, few-shot examples...
└── mcp-server-sqlseed/      # MCP server — AI assistant integration
    └── src/mcp_server_sqlseed/   # FastMCP tools (sqlseed_generate_yaml/sqlseed_execute_fill)
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
| `sqlseed` | sqlalchemy, pydantic, pluggy, structlog, pyyaml, faker, typing_extensions, simpleeval, **rstr** | faker is required core dep; rstr used for `pattern` generator regex matching |
| `sqlseed[mimesis]` | + mimesis>=18.0 | Mimesis data engine (recommended) |
| `sqlseed[postgres]` | + psycopg | PostgreSQL driver for SQLAlchemy |
| `sqlseed[docs]` | + mkdocs-material, mkdocstrings | Documentation build |
| `sqlseed-ai` | sqlseed, **openai>=1.0** | AI plugin (Gemma 4 Native Function Calling), auto-registered via entry-point |
| `sqlseed-ai[mcp]` | + sqlseed-ai, **mcp>=1.0** | AI MCP server (4 LLM tools); install with `pip install "sqlseed-ai[mcp]"` |
| `mcp-server-sqlseed` | sqlseed, **mcp>=1.0** | MCP server (2 core tools, no LLM), standalone CLI tool |

***

## 📄 License

[AGPL-3.0-or-later](LICENSE)

***

<div align="center">

**🌱 sqlseed** — *Stop writing fixtures. Start generating data.*

</div>
