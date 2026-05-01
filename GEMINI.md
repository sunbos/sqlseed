# sqlseed - Project Context

## Project Overview
`sqlseed` is a declarative SQLite test data generation toolkit written in Python (>=3.10). It intelligently generates large volumes of high-quality test data with minimal configuration. The tool automatically infers database schemas and selects appropriate data generation strategies, while offering fine-grained control via Python API or declarative YAML/JSON configuration.

Core features include:
- High-performance data generation engines: Mimesis (recommended) and Faker
- 9-level strategy chain for intelligent column mapping (including enum inference, unique adaptivity, etc.)
- Automatic foreign key resolution and topological sort dependency management
- SQLite PRAGMA bulk write optimization (`PragmaOptimizer` with LIGHT / MODERATE / AGGRESSIVE strategies)
- Robust plugin architecture based on `pluggy` with 11 lifecycle hooks
- Official AI-powered plugin (`sqlseed-ai`) for LLM-driven data generation
- MCP server (`mcp-server-sqlseed`) for AI assistant integration via Model Context Protocol (default locale: `en_US`)
- Cross-table SharedPool for referential integrity
- Secure expression engine with timeout-protected derived column computation and backtracking constraint solving
- Snapshot replay mechanism for reproducible data generation

## Project Architecture
- **Root directory**: Contains CI/CD and publishing GitHub Actions workflows (`.github/`) along with PR/Issue template instructions.
- **`src/sqlseed/core/`**: Core orchestrator engine handling main flow orchestration (`orchestrator.py`), generation result statistics (`result.py`), schema inference (`schema.py`), strategy mapping (`mapper.py`), relation resolution (`relation.py`), column dependency DAG (`column_dag.py`), expression evaluation (`expression.py`), constraint solving (`constraints.py`), transform loading (`transform.py`), column data enrichment (`enrichment.py`), unique strategy adjustment (`unique_adjuster.py`), and plugin/AI suggestion mediation (`plugin_mediator.py`).
- **`src/sqlseed/generators/`**: Data provider registry and generator implementations (`mimesis_provider.py`, `faker_provider.py`) with streaming generation adapter (`stream.py`). Includes protocol definitions (`_protocol.py`), base implementation (`base_provider.py`), registration mechanism (`registry.py`), and internal helpers (`_dispatch.py`, `_json_helpers.py`, `_string_helpers.py`).
- **`src/sqlseed/database/`**: SQLite interaction adapter base class (`_base_adapter.py`) with concrete implementations (`sqlite_utils_adapter.py` and `raw_sqlite_adapter.py`), including PRAGMA optimization (`optimizer.py`). Protocol (`_protocol.py`) defines `ColumnInfo`, `ForeignKeyInfo`, `IndexInfo` metadata and data query methods, plus internal helpers (`_compat.py`, `_helpers.py`).
- **`src/sqlseed/plugins/`**: Plugin management and hook specification definitions based on `pluggy` (`hookspecs.py` and `manager.py`).
- **`src/sqlseed/config/`**: Configuration management using `pydantic` models, YAML/JSON loader (`loader.py`, `models.py`), and runtime snapshots supporting CLI `replay` command (`snapshot.py`).
- **`src/sqlseed/cli/`**: `click`-based command-line interface (`main.py` providing fill, preview, inspect, init, replay, ai-suggest).
- **`src/sqlseed/_utils/`**: Internal utilities including SQL safety (`sql_safe.py`), shared schema helpers (`schema_helpers.py`), performance metrics collection (`metrics.py`), progress bar wrapper (`progress.py`, based on `rich`), and logging wrapper (`logger.py`, based on `structlog`).
- **`plugins/sqlseed-ai/`**: Standalone package providing OpenAI-compatible LLM-driven generation. Contains `analyzer.py` (LLM table-level analysis), `refiner.py` (self-correction loop), `errors.py` (error summary), `examples.py` (few-shot examples), `provider.py` (AI provider compatibility stub), `config.py` (AIConfig model), `_client.py` (API client), `_json_utils.py` (JSON parsing), and `_model_selector.py` (auto model selection from OpenRouter).
- **`plugins/mcp-server-sqlseed/`**: MCP server based on FastMCP providing one Resource (`sqlseed://schema/{db_path}/{table_name}`) and three core Tools (`sqlseed_inspect_schema`, `sqlseed_generate_yaml`, `sqlseed_execute_fill`) for seamless AI assistant integration (driven by `server.py` and `config.py`).
- **`docs/`**: Project documentation including architecture diagrams (`architecture.md`).

## Build & Run
The project uses `hatch` as the build backend and package manager.

**Installation:**
```bash
# Install core and all optional dependencies (Mimesis, Faker)
pip install -e ".[dev,all]"

# Install AI plugin (optional)
pip install -e "./plugins/sqlseed-ai"

# Install MCP server (optional)
pip install -e "./plugins/mcp-server-sqlseed"
```

**CLI Usage Examples:**
```bash
# Generate data (--count required when not using --config)
sqlseed fill test.db --table users --count 10000

# YAML config-driven generation (count from config file)
sqlseed fill --config generate.yaml

# Preview data (no write)
sqlseed preview test.db --table users --count 5

# Inspect database tables and column mapping strategies
sqlseed inspect test.db --table users --show-mapping

# Generate config template
sqlseed init generate.yaml --db test.db

# Save and replay snapshots
sqlseed fill test.db --table users --count 10000 --snapshot
sqlseed replay snapshots/2026-04-12_users.yaml

# AI-driven YAML suggestions
sqlseed ai-suggest test.db --table users --output users.yaml

# Enable debug logging
SQLSEED_LOG_LEVEL=DEBUG sqlseed fill test.db --table users --count 10
```

**Python API Usage Examples:**
```python
import sqlseed

# Simple fill
result = sqlseed.fill("test.db", table="users", count=1000)
print(f"Elapsed: {result.elapsed:.2f}s, Inserted: {result.count} rows")

# Using Orchestrator (context manager)
with sqlseed.connect("test.db", provider="mimesis") as db:
    db.fill("users", count=5000)
```

## Development Guidelines
- **Testing (`pytest`)**: The project maintains ~94% test coverage. The `tests/` directory includes top-level public API and integration tests (`test_public_api.py`, `test_cli.py`, `test_orchestrator.py`, `test_ai_plugin.py`, etc.), module-specific subdirectory tests (`test_config`, `test_core`, `test_database`, `test_generators`, `test_plugins`, `test_utils`), and performance benchmarks (`benchmarks/`). Key coverage includes constraint backtracking (`ConstraintSolver`), thread-safe derived column evaluation engine, and recursive fallback deduplication logic.
  - Run tests: `pytest`
  - Run with verbose traceback: `pytest --tb=long -v`
  - AI plugin tests use `pytest.importorskip("sqlseed_ai")` for optional dependency handling.
- **Linting & Formatting (`ruff`)**: Strict code checking rules applied (config in `pyproject.toml` `[tool.ruff]`).
  - Run lint: `ruff check src/ tests/ plugins/`
- **Type Checking (`mypy`)**: Strict static typing is a core requirement.
  - Run type check: `mypy src/sqlseed/ plugins/`
- **Design Philosophy**: The codebase embraces Protocol-driven design (`typing.Protocol`), explicit configuration (`pydantic`), and high extensibility through the hook system. Unsafe operations are encapsulated in `_utils` modules (e.g., `sql_safe.py`).
- **Expression Safety**: `ExpressionEngine` uses `simpleeval` with isolated copies and multi-threaded timeout protection for concurrency safety, preventing infinite loops or variable pollution in user-provided derived column configs.
