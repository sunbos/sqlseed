# Changelog

**[English](CHANGELOG.md)** | [中文](CHANGELOG.zh-CN.md)

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.1.13]

### Added

#### Core Engine
- Cross-table association support: `ColumnAssociation` config model for explicit source table/column mapping
- Implicit association: `SharedPool` auto-matches cross-table FK references by shared column names
- `EnrichmentEngine` data distribution inference — detects enum columns and value ranges from existing data
- `UniqueAdjuster` auto-tunes unique column parameters to satisfy UNIQUE constraints
- `database/_compat.py` adds `HAS_SQLITE_UTILS` flag for runtime sqlite-utils detection

#### Generators
- 7 new generator types: `username`, `city`, `country`, `state`, `zip_code`, `job_title`, `country_code`
- `ColumnMapper` exact match rules expanded from 68 to 74

#### AI Plugin (sqlseed-ai)
- Auto model selection: `_model_selector` picks the best free model from OpenRouter by priority
- Structured output: `response_format: json_object` forces LLM to return JSON
- Few-shot example library: 4 typical scenarios (users, bank cards, orders, employees)
- `AiConfigRefiner` self-correction loop: auto-detects and fixes invalid configs, up to 3 retries
- File caching: `.sqlseed_cache/ai_configs/` with schema hash validation, `--no-cache` to skip
- Pre-computed template pool: `sqlseed_pre_generate_templates` hook pre-generates candidate values for complex columns
- Error summary system: `errors.py` smart error classification
- Environment variables: `SQLSEED_AI_API_KEY`, `SQLSEED_AI_BASE_URL`, `SQLSEED_AI_MODEL`, `SQLSEED_AI_TIMEOUT`

#### MCP Server (mcp-server-sqlseed)
- `sqlseed_execute_fill` adds `enrich` parameter for data distribution inference
- `sqlseed_inspect_schema` returns `schema_hash` field

#### CLI
- `fill` command adds `--enrich` flag
- `fill` command adds `--no-ai` flag to skip AI suggestions and template generation
- `ai-suggest` command adds `--verify/--no-verify` and `--timeout` parameters
- `fill` command makes `db_path` optional when using `--config`

#### Tests & Examples
- Add `test_cli_yaml_priority.py` covering CLI YAML priority scenarios
- Add `examples/ai_generation_demo.py` usage example

### Changed

- Simplify `ExpressionEngine` regex patterns
- Optimize code structure and type annotations, remove unnecessary lazy imports
- CI workflows expanded: ruff check covers `plugins/` directory, add concurrency control
- Update dependency version constraints
- Rewrite all project documentation: CLAUDE.md, README.md, GEMINI.md, AGENTS.md, architecture.md
- Rewrite `plugins/sqlseed-ai/README.md` and `plugins/mcp-server-sqlseed/README.md`

### Fixed

- ruff lint cleanup, allow Chinese fullwidth characters (`：`, `（`, `）`)
- Remove unnecessary `sqlite3.OperationalError` catch
- `ProviderRegistry.register_from_entry_points()` fixes non-provider entry point detection

### Removed

- Remove `docs/superpowers/` directory (outdated design specs)
- Remove `suggest.py` and `nl_config.py`, replaced by `SchemaAnalyzer` + `AiConfigRefiner`

## [v0.1.12]

### Added

#### Core Engine
- Core orchestrator `DataOrchestrator` with streaming batch generation
- `ColumnMapper` 9-level strategy chain (exact match → pattern match → type fallback → default)
- `DatabaseAdapter` Protocol with `SQLiteUtilsAdapter` and `RawSQLiteAdapter`
- `PragmaOptimizer` 3-tier optimization (LIGHT / MODERATE / AGGRESSIVE)
- `DataProvider` Protocol with `BaseProvider`, `FakerProvider`, `MimesisProvider`
- `DataStream` memory-efficient streaming data generator
- `RelationResolver` foreign key dependency topological sort
- Plugin system based on `pluggy` with 11 hook points
- CLI commands: `fill`, `preview`, `inspect`, `init`, `replay`, `ai-suggest`
- Python API: `sqlseed.fill()`, `sqlseed.connect()`, `sqlseed.fill_from_config()`, `sqlseed.preview()`
- YAML/JSON config file support
- Config snapshot save and replay
- SQL injection protection (`quote_identifier()` utility)

#### v2.0 — Column DAG & Expression Engine
- `ColumnDAG` column dependency resolution via topological sort
- `ExpressionEngine` safe expression evaluation via `simpleeval` with thread-based timeout protection
- `ConstraintSolver` unique constraint solving with retry and backtracking
- `TransformLoader` dynamic Python script loading (`importlib`)
- `SharedPool` cross-table value sharing for referential integrity
- `IndexInfo` dataclass and `get_index_info()` added to `DatabaseAdapter` Protocol
- `get_sample_rows()` method added to `DatabaseAdapter` Protocol for context sniffing
- `sqlseed_ai_analyze_table` hook (firstresult) for AI-driven schema analysis
- `sqlseed_shared_pool_loaded` hook for cross-table association tracking

#### AI Plugin (sqlseed-ai)
- `SchemaAnalyzer` LLM integration (OpenAI-compatible API)
- Context sniffing: extracts columns, indexes, sample data, foreign keys for LLM analysis
- `AIConfig` configurable model, API key, and base URL
- CLI `ai-suggest` command for AI-driven YAML generation

#### MCP Server (mcp-server-sqlseed)
- `sqlseed_inspect_schema` tool — inspect database schema
- `sqlseed_generate_yaml` tool — AI-driven YAML config generation
- `sqlseed_execute_fill` tool — execute data generation
- FastMCP-based server

### Fixed
- Hook `firstresult` semantics aligned with design docs
- `validate_table_name` adds regex validation
- Expression engine adds timeout protection (default 5 seconds)
- `fill_from_config` correctly passes transform attribute
