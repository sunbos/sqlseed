# sqlseed - Project Context

## Project Overview
`sqlseed` is a declarative SQLite test data generation toolkit written in Python (>=3.10). It is designed to intelligently generate large volumes of high-quality test data with minimal configuration. The tool can automatically infer database schemas and select appropriate data generation strategies, while also providing granular control via Python APIs or declarative YAML/JSON configurations. 

Key features include:
- Support for high-performance data generation engines like Mimesis (recommended) and Faker.
- Intelligent column mapping through an 8-level strategy chain.
- Automatic foreign key resolution and topological sorting for dependency management.
- SQLite PRAGMA optimizations for batch processing.
- A robust plugin architecture powered by `pluggy` with 9 lifecycle hooks.
- An official AI-powered plugin (`sqlseed-ai`) for LLM-driven data generation.

## Project Architecture
- **`src/sqlseed/core/`**: The core orchestration engine, handling schema inference (`schema.py`), strategy mapping (`mapper.py`), and relation resolution (`relation.py`).
- **`src/sqlseed/generators/`**: Data provider registry and adapters for Mimesis, Faker, and stream-based generation.
- **`src/sqlseed/database/`**: Adapters for SQLite interactions (`sqlite-utils` and raw `sqlite3`), including PRAGMA optimizations.
- **`src/sqlseed/plugins/`**: Plugin management and hook specifications defined via `pluggy`.
- **`src/sqlseed/config/`**: Configuration management using `pydantic` models and YAML/JSON loaders.
- **`src/sqlseed/cli/`**: The command-line interface implemented with `click`.
- **`plugins/sqlseed-ai/`**: A distinct package providing OpenAI-powered generation capabilities.

## Building and Running
The project uses `hatch` as its build backend and package manager. 

**Installation:**
```bash
# Install core with development and all optional dependencies (Mimesis, Faker)
pip install -e ".[dev,all]"

# Install the AI plugin (optional)
pip install -e "./plugins/sqlseed-ai"
```

**CLI Usage Examples:**
```bash
# Zero-config generation
sqlseed fill test.db --table users --count 10000

# YAML-driven generation
sqlseed fill --config generate.yaml

# Data preview without writing to DB
sqlseed preview test.db --table users --count 5
```

## Development Conventions
- **Testing (`pytest`)**: The project maintains comprehensive test coverage (unit, integration, CLI, and snapshot tests). 
  - Run tests with: `pytest` (configured with `--cov=sqlseed` by default).
- **Linting & Formatting (`ruff`)**: Strict linting rules are enforced.
  - Run linting with: `ruff check src/ tests/`
- **Type Checking (`mypy`)**: Strict static typing is a core requirement.
  - Run type checking with: `mypy src/sqlseed/`
- **Design Philosophy**: The codebase favors protocol-driven design (`typing.Protocol`), explicit configuration (`pydantic`), and high extensibility through its hook system. Unsafe operations are contained within the `_utils` module (e.g., `sql_safe.py`).