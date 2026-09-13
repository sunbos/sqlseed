# Multi-Database Support Test Completion Design

**Date:** 2026-06-20
**Branch:** `feat/multi-db-support`
**Status:** Design confirmed, pending implementation plan
**Prerequisites:** Phase 1-4 multi-database migration completed (commits 21ddd98 → 63d8ddf → a0079f2 → 407e252)

## 1. Background and Goals

### 1.1 Problem Statement

The multi-database support feature (Phase 1-4) has been completed, and all 720 existing tests pass. However, investigation revealed **approximately 156 test gaps**, concentrated in:

- **Phase 3 core functionality has zero coverage**: URL connection, CLI `--url`, `GeneratorConfig.url`, MCP URL support, `NoSuchModuleError`/`ArgumentError` friendly messages — all without tests
- **SQLAlchemyAdapter boundaries untested**: non-existent tables returning empty values (7 methods just fixed but untested), operations after close, empty databases
- **DatabaseAdapterContract framework exists but is empty**, no guarantee of behavioral consistency between the two adapters
- **MCP server has no test directory at all**, 6 tools + 1 resource all running naked
- **AI plugin dialect context propagation untested**, PG schema analysis may not distinguish dialect features
- **No real PG/LLM integration tests**, all PG tests are mocks

### 1.2 Design Goals

1. **Comprehensive coverage**: Fill all ~156 test gaps across P0+P1+P2
2. **Real environment validation**: PG integration uses testcontainers to start real containers; AI tests use real LLM calls (Gemma 4)
3. **Clear failure messages**: Tests fail (not skip) when Docker/LLM is missing, with environment setup guidance
4. **Merge threshold**: All new tests + 720 existing tests pass, and merge to main only after explicit user confirmation

### 1.3 Non-Goals

- No source code modifications (pure test completion)
- No adjustment to MCP server responsibility boundaries (the "focus on data generation" positioning is confirmed correct)
- No new features

## 2. Overall Architecture

### 2.1 Test File Layout

Add **8 new test files** + extend **11 existing files**:

```
tests/
├── test_database/
│   ├── test_sqlalchemy_adapter.py          # Extend: +URL/boundary test classes
│   ├── test_dialect.py                      # Extend: +MySQL types/PG boundaries/TypeNormalizer boundaries
│   ├── test_optimizer.py                    # Extend: migrate to BulkWriteOptimizer abstraction
│   ├── test_adapter_contract.py             # New: DatabaseAdapterContract implementation
│   ├── test_sqlalchemy_adapter_boundary.py  # New: non-existent tables/after close/empty DB/reserved words
│   └── test_sqlalchemy_adapter_url.py       # New: URL connection/missing driver/invalid URL
├── test_url_connection.py                   # New: public API url parameter
├── test_orchestrator_adapter.py             # New: _create_adapter/_is_db_url/_get_dialect_name
├── test_config/
│   ├── test_models.py                       # Extend: +TestGeneratorConfigUrl
│   └── test_loader.py                       # Extend: +TestReadSqliteTableNames
├── test_cli.py                              # Extend: +TestCLIUrlOption
├── test_ai_plugin.py                        # Extend: +TestSchemaAnalyzerDialect (real LLM)
├── test_orchestrator.py                     # Extend: +TestOrchestratorCountValidation
└── integration/                             # New directory
    ├── __init__.py
    ├── conftest.py                          # PG testcontainers + LLM backend detection fixtures
    ├── test_pg_integration.py               # New: real PG integration tests
    └── test_url_e2e.py                      # New: URL end-to-end E2E

plugins/mcp-server-sqlseed/tests/            # New directory
├── __init__.py
├── conftest.py
├── test_validate_db_path.py                 # New: URL/file path validation
└── test_server.py                           # New: 6 tools + 1 resource tests (with real LLM)
```

### 2.2 Three Checkpoints

| Checkpoint | Content | New Tests | Validation Threshold |
|------------|---------|-----------|----------------------|
| **CP1 (P0)** | URL connection/CLI --url/Config.url/MCP URL/NoSuchModuleError/ArgumentError | ~60 | Full pytest passes |
| **CP2 (P1)** | Boundary cases/DatabaseAdapterContract/AI dialect (real LLM)/loader/count validation | ~48 | Full pytest passes |
| **CP3 (P2)** | Reserved words/real PG integration/URL E2E/optimizer migration/MCP complete tools (real LLM) | ~48 | Full pytest passes |
| **Total** | | **~156** | All pass before merge + user confirmation |

### 2.3 Real Environment Dependencies

| Dependency | Purpose | Behavior When Missing |
|------------|---------|------------------------|
| Docker | testcontainers starts real PG container | fail with prompt to install Docker |
| LLM backend (Ollama/LM Studio/Google AI Studio) | AI plugin real LLM calls | fail with prompt for configuration |
| psycopg[binary] | PG driver | dev dependency already included |

## 3. Checkpoint 1 (P0) — Core New Features

### 3.1 URL Connection Tests

**File:** `tests/test_url_connection.py` (new)
**Class:** `TestPublicAPIUrl`
**Test count:** ~15

| Test | Description |
|------|-------------|
| `test_fill_with_url_sqlite` | `fill(url="sqlite:///path.db", table=..., count=10)` writes successfully |
| `test_connect_with_url` | `connect(url="sqlite:///path.db")` returns orchestrator, can fill |
| `test_preview_with_url` | `preview(url="sqlite:///path.db", ...)` returns preview data |
| `test_fill_url_and_db_path_mutual_exclusion` | Providing both raises ValueError |
| `test_fill_no_target_raises` | Providing neither raises ValueError |
| `test_fill_with_url_writes_correct_data` | Verify written data structure matches db_path mode |
| `test_connect_with_url_context_manager` | `with connect(url=...) as orch:` works correctly |
| `test_preview_with_url_returns_list` | Returns list[dict] |
| `test_fill_with_url_snapshot` | snapshot functionality works in url mode |
| `test_fill_with_url_config_file` | fill_from_config uses url field |
| `test_resolve_db_target_priority` | db_path takes priority over url (when only db_path is provided) |
| `test_resolve_db_target_url_only` | Returns correctly when only url is provided |
| `test_fill_with_url_invalid_table_raises` | Non-existent table in url mode reports error correctly |
| `test_fill_with_url_count_zero_raises` | count=0 in url mode raises ValueError |
| `test_fill_with_url_seed_reproducibility` | seed is reproducible in url mode |

### 3.2 SQLAlchemyAdapter URL Tests

**File:** `tests/test_database/test_sqlalchemy_adapter_url.py` (new)
**Class:** `TestSQLAlchemyAdapterUrl`
**Test count:** ~12

| Test | Description |
|------|-------------|
| `test_connect_sqlite_file_url` | `connect("sqlite:///path.db")` succeeds |
| `test_connect_sqlite_memory_url` | `connect("sqlite://")` memory DB succeeds |
| `test_connect_postgresql_url_with_testcontainers` | Real PG container connection succeeds (depends on pg_url fixture) |
| `test_connect_postgresql_missing_driver` | When psycopg not installed, raises RuntimeError containing "pip install sqlseed[postgres]" |
| `test_connect_mysql_missing_driver` | When pymysql not installed, raises RuntimeError containing "pip install sqlseed[mysql]" |
| `test_connect_invalid_url_raises_value_error` | `connect("not_a_url")` raises ValueError |
| `test_connect_malformed_url_raises_value_error` | `connect("postgresql://")` raises ValueError |
| `test_connect_unsupported_dialect` | `connect("oracle://...")` raises ValueError |
| `test_connect_url_sets_dialect_correctly_sqlite` | dialect.name == "sqlite" |
| `test_connect_url_sets_dialect_correctly_postgresql` | dialect.name == "postgresql" (real PG) |
| `test_connect_url_persists_engine` | engine reusable after connection |
| `test_connect_url_close_releases_resources` | engine released after close |

### 3.3 CLI --url Tests

**File:** `tests/test_cli.py` (extended)
**Class:** `TestCLIUrlOption`
**Test count:** ~10

| Test | Description |
|------|-------------|
| `test_fill_with_url_sqlite` | `sqlseed fill --url "sqlite:///path.db" -t users -n 10` succeeds |
| `test_fill_with_url_and_db_path_mutual_exclusion` | Providing both raises UsageError |
| `test_fill_without_url_or_db_path_errors` | Providing neither raises UsageError |
| `test_preview_with_url` | `sqlseed preview --url "sqlite:///path.db" -t users -n 5` succeeds |
| `test_inspect_with_url` | `sqlseed inspect --url "sqlite:///path.db"` succeeds |
| `test_fill_url_output_format` | Output format in url mode matches db_path mode |
| `test_fill_url_with_config` | `--url` and `--config` can coexist |
| `test_fill_url_postgresql_missing_driver` | PG URL missing driver gives friendly CLI error |
| `test_fill_url_verbose_mode` | Verbose output in url mode is correct |
| `test_fill_url_snapshot_flag` | `--snapshot` works in url mode |

### 3.4 GeneratorConfig.url Tests

**File:** `tests/test_config/test_models.py` (extended)
**Class:** `TestGeneratorConfigUrl`
**Test count:** ~8

| Test | Description |
|------|-------------|
| `test_url_field_accepted` | `GeneratorConfig(url="postgresql://...", tables=[...])` succeeds |
| `test_db_path_and_url_mutual_exclusion` | Providing both raises ValidationError |
| `test_neither_db_path_nor_url_raises` | Providing neither raises ValidationError |
| `test_connection_target_returns_url` | `config.connection_target` returns url |
| `test_connection_target_returns_db_path` | `config.connection_target` returns db_path |
| `test_connection_target_property_consistency` | Multiple calls return the same value |
| `test_from_config_uses_connection_target` | from_config uses connection_target instead of db_path |
| `test_config_with_url_serialization` | YAML with url field loads correctly |

### 3.5 MCP server URL Tests

**File:** `plugins/mcp-server-sqlseed/tests/test_validate_db_path.py` (new)
**Class:** `TestValidateDbPath`
**Test count:** ~8

| Test | Description |
|------|-------------|
| `test_validate_postgresql_url_passes_through` | `"postgresql://user:pass@host/db"` returns directly |
| `test_validate_mysql_url_passes_through` | `"mysql://..."` returns directly |
| `test_validate_sqlite_url_passes_through` | `"sqlite:///path.db"` returns directly |
| `test_validate_invalid_file_path_raises` | `"not_a_url"` raises ValueError |
| `test_validate_nonexistent_db_file_raises` | `"missing.db"` raises ValueError |
| `test_validate_valid_sqlite_file_returns_resolved` | Real .db file returns absolute path |
| `test_validate_url_with_special_chars` | URL with special characters (passwords etc.) handled correctly |
| `test_validate_url_scheme_only_no_authority` | `"postgresql://"` boundary handling |

### 3.6 orchestrator adapter dispatch tests

**File:** `tests/test_orchestrator_adapter.py` (new)
**Class:** `TestOrchestratorAdapter`
**Test count:** ~7

| Test | Description |
|------|-------------|
| `test_is_db_url_with_postgresql` | `_is_db_url("postgresql://...")` returns True |
| `test_is_db_url_with_mysql` | `_is_db_url("mysql://...")` returns True |
| `test_is_db_url_with_file_path` | `_is_db_url("/path/to/db.sqlite")` returns False |
| `test_is_db_url_with_relative_path` | `_is_db_url("app.db")` returns False |
| `test_create_adapter_returns_sqlalchemy_for_url` | URL input returns SQLAlchemyAdapter instance |
| `test_create_adapter_returns_sqlalchemy_for_file` | File path returns SQLAlchemyAdapter instance |
| `test_get_dialect_name_sqlite` | SQLite file returns "sqlite" |

**CP1 total: ~60 tests**

## 4. Checkpoint 2 (P1) — Boundary Cases and Robustness

### 4.1 SQLAlchemyAdapter Boundary Tests

**File:** `tests/test_database/test_sqlalchemy_adapter_boundary.py` (new)
**Class:** `TestSQLAlchemyAdapterBoundary`
**Test count:** ~15

| Test | Description |
|------|-------------|
| `test_get_column_info_nonexistent_table_returns_empty` | Non-existent table returns `[]` |
| `test_get_primary_keys_nonexistent_table_returns_empty` | Returns `[]` |
| `test_get_foreign_keys_nonexistent_table_returns_empty` | Returns `[]` |
| `test_get_index_info_nonexistent_table_returns_empty` | Returns `[]` |
| `test_get_row_count_nonexistent_table_returns_zero` | Returns 0 |
| `test_get_column_values_nonexistent_table_returns_empty` | Returns `[]` |
| `test_get_sample_rows_nonexistent_table_returns_empty` | Returns `[]` |
| `test_batch_insert_nonexistent_table_raises_runtime_error` | Raises RuntimeError (not NoSuchTableError) |
| `test_operation_after_close_raises` | Calling get_table_names after close raises RuntimeError |
| `test_operation_after_context_exit_raises` | Operation after `with` exit raises RuntimeError |
| `test_empty_database_get_table_names_returns_empty` | Empty database returns `[]` |
| `test_connect_to_nonexistent_sqlite_file_creates_it` | SQLite auto-creates file |
| `test_double_connect_raises` | Repeated connect raises RuntimeError |
| `test_close_idempotent` | Multiple close does not error |
| `test_dialect_accessible_before_connect_raises` | Accessing dialect before connection raises RuntimeError |

### 4.2 DatabaseAdapterContract Implementation

**File:** `tests/test_database/test_adapter_contract.py` (new)
**Base class:** `DatabaseAdapterContract` (14 contract tests)
**Subclasses:** `TestRawSQLiteContract`, `TestSQLAlchemyContract`
**Test count:** 14 × 2 = 28

**DatabaseAdapterContract contract tests:**

| Test | Description |
|------|-------------|
| `test_get_table_names` | Returns all user tables |
| `test_get_column_info_structure` | ColumnInfo fields complete |
| `test_get_primary_keys_correct` | Correctly identifies PK |
| `test_get_foreign_keys_correct` | Correctly identifies FK |
| `test_batch_insert_and_count` | Row count correct after insert |
| `test_batch_insert_large` | Large batch insert (1000 rows) |
| `test_clear_table_resets_count` | Row count is 0 after clear |
| `test_clear_table_resets_autoincrement` | Auto-increment starts from 1 after clear |
| `test_get_row_count_empty_table` | Empty table returns 0 |
| `test_get_sample_rows_structure` | Returns list[dict] |
| `test_get_column_values_correct` | Returns correct column values |
| `test_get_index_info_correct` | Correctly identifies indexes |
| `test_execute_select` | execute returns cursor |
| `test_nonexistent_table_returns_empty` | Non-existent table returns empty values |

**Subclass implementations:**
- `TestRawSQLiteContract(DatabaseAdapterContract)` — uses RawSQLiteAdapter
- `TestSQLAlchemyContract(DatabaseAdapterContract)` — uses SQLAlchemyAdapter

### 4.3 AI plugin dialect context tests (real LLM calls)

**File:** `tests/test_ai_plugin.py` (extended)
**Class:** `TestSchemaAnalyzerDialect`
**Test count:** ~8

**Pure string validation tests (no LLM calls):**

| Test | Description |
|------|-------------|
| `test_build_context_with_sqlite_dialect` | dialect="sqlite" output contains "Database dialect: sqlite" |
| `test_build_context_with_postgresql_dialect` | dialect="postgresql" output contains "Database dialect: postgresql" |
| `test_build_context_default_dialect_is_sqlite` | Default dialect is "sqlite" when not passed |

**Real LLM call tests (depend on `available_llm_backend` fixture):**

| Test | Description |
|------|-------------|
| `test_analyze_schema_sqlite_real_llm` | Real SQLite schema analysis, verify LLM returns valid YAML |
| `test_analyze_schema_postgresql_real_llm` | Real PG schema analysis (uses pg_url fixture), verify dialect propagates to LLM prompt |
| `test_analyze_schema_dialect_in_prompt` | Capture actual prompt sent to LLM, assert contains "Database dialect: postgresql" |
| `test_analyze_schema_llm_response_structure` | Verify LLM return structure (tables/columns/generators) |
| `test_analyze_schema_llm_failure_clear_error` | Simulate LLM timeout/error, error message provides clear guidance |

### 4.4 config/loader.py tests

**File:** `tests/test_config/test_loader.py` (extended)
**Class:** `TestReadSqliteTableNames`
**Test count:** ~5

| Test | Description |
|------|-------------|
| `test_read_sqlite_table_names_empty_database` | Empty database returns `[]` |
| `test_read_sqlite_table_names_excludes_system_tables` | Excludes sqlite_% tables |
| `test_read_sqlite_table_names_returns_all_user_tables` | Multi-table database returns all |
| `test_generate_template_with_url_skips_table_read` | URL config does not read tables (avoids connecting to remote DB) |
| `test_read_sqlite_table_names_nonexistent_file_raises` | Non-existent file raises exception |

### 4.5 orchestrator count validation tests

**File:** `tests/test_orchestrator.py` (extended)
**Class:** `TestOrchestratorCountValidation`
**Test count:** ~4

| Test | Description |
|------|-------------|
| `test_fill_count_zero_raises` | `fill_table(count=0)` raises ValueError |
| `test_fill_count_negative_raises` | `fill_table(count=-1)` raises ValueError |
| `test_fill_count_one_succeeds` | count=1 generates normally |
| `test_fill_count_large_succeeds` | count=10000 generates normally (no error) |

### 4.6 TypeNormalizer Boundary Tests

**File:** `tests/test_database/test_dialect.py` (extended)
**Test count:** ~4

| Test | Description |
|------|-------------|
| `test_normalize_none_input` | `normalize(None, "sqlite")` handles None |
| `test_normalize_whitespace_only` | `normalize("   ", "sqlite")` handles pure whitespace |
| `test_normalize_unknown_dialect` | `normalize("int", "oracle")` goes through default uppercase branch |
| `test_normalize_empty_string` | `normalize("", "postgresql")` handles empty string |

### 4.7 MySQL Type Mapping Completion

**File:** `tests/test_database/test_dialect.py` (extended)
**Test count:** ~8

| Test | Description |
|------|-------------|
| `test_mysql_int_mapping` | INT → INTEGER |
| `test_mysql_bigint_mapping` | BIGINT → BIGINT |
| `test_mysql_varchar_mapping` | VARCHAR(255) → VARCHAR |
| `test_mysql_text_mapping` | TEXT → TEXT |
| `test_mysql_datetime_mapping` | DATETIME → DATETIME |
| `test_mysql_tinyint_mapping` | TINYINT → TINYINT |
| `test_mysql_decimal_mapping` | DECIMAL(10,2) → DECIMAL |
| `test_mysql_json_mapping` | JSON → JSON |

**CP2 total: ~48 tests**

## 5. Checkpoint 3 (P2) — Enhanced Coverage and Real Integration

### 5.1 Real PostgreSQL Integration Tests

**File:** `tests/integration/test_pg_integration.py` (new)
**Class:** `TestPostgreSQLIntegration`
**Dependency:** `pg_url` fixture (testcontainers starts real PG container)
**Test count:** ~12

| Test | Description |
|------|-------------|
| `test_pg_connect_and_close` | Real PG connect/close |
| `test_pg_get_table_names_empty` | Empty PG database returns `[]` |
| `test_pg_create_table_and_get_column_info` | After creating table, get_column_info correctly identifies types |
| `test_pg_serial_autoincrement_detection` | SERIAL column identified as autoincrement |
| `test_pg_bigserial_autoincrement_detection` | BIGSERIAL column identified as autoincrement |
| `test_pg_identity_autoincrement_detection` | GENERATED AS IDENTITY column identified as autoincrement |
| `test_pg_batch_insert_and_count` | Row count correct after batch insert |
| `test_pg_clear_table_resets_sequence` | Sequence reset after clear_table (real pg_get_serial_sequence) |
| `test_pg_fill_end_to_end` | `fill(url=pg_url, table=..., count=100)` complete flow |
| `test_pg_fill_with_fk_integrity` | FK-related table data integrity on PG |
| `test_pg_bulk_optimizer_synchronous_commit` | Verify synchronous_commit=OFF takes effect (query current value) |
| `test_pg_dialect_in_schema_context` | get_schema_context on PG returns dialect="postgresql" |

### 5.2 URL End-to-End E2E Tests

**File:** `tests/integration/test_url_e2e.py` (new)
**Class:** `TestUrlE2E`
**Test count:** ~6

| Test | Description |
|------|-------------|
| `test_cli_url_to_pg_e2e` | `sqlseed fill --url pg_url -t users -n 100` complete CLI→PG flow |
| `test_api_url_to_pg_e2e` | `fill(url=pg_url, ...)` complete API→PG flow |
| `test_config_url_to_pg_e2e` | YAML with url field → fill_from_config → PG |
| `test_pg_url_snapshot_and_replay` | Snapshot save + replay on PG |
| `test_pg_url_preview_e2e` | `preview(url=pg_url, ...)` returns correct preview |
| `test_pg_url_inspect_e2e` | `inspect(url=pg_url)` shows mapping strategy |

### 5.3 Reserved Words and Special Characters Tests

**File:** `tests/test_database/test_sqlalchemy_adapter_boundary.py` (extended)
**Class:** `TestReservedWordsAndSpecialChars`
**Test count:** ~6

| Test | Description |
|------|-------------|
| `test_table_name_reserved_word_order` | Table name "order" (SQL reserved word) correctly quoted |
| `test_table_name_reserved_word_select` | Table name "select" correctly quoted |
| `test_column_name_reserved_word` | Column names "from", "where" correctly quoted |
| `test_table_name_with_special_chars` | Table name with double quotes correctly escaped |
| `test_column_name_with_special_chars` | Column name with double quotes correctly escaped |
| `test_fill_table_with_reserved_name_e2e` | Reserved word table name complete fill flow |

### 5.4 SQLAlchemyAdapter vs RawSQLiteAdapter Consistency

**File:** `tests/test_database/test_adapter_contract.py` (extended)
**Class:** `TestAdapterConsistency`
**Test count:** ~4

| Test | Description |
|------|-------------|
| `test_both_adapters_same_column_info` | Both adapters return same ColumnInfo for same DB |
| `test_both_adapters_same_row_count` | Both adapters return same row count for same DB |
| `test_both_adapters_same_foreign_keys` | Both adapters return same FK for same DB |
| `test_both_adapters_same_sample_rows` | Both adapters return same sample rows for same DB |

### 5.5 PostgresDialect Boundary Tests

**File:** `tests/test_database/test_dialect.py` (extended)
**Test count:** ~4

| Test | Description |
|------|-------------|
| `test_pg_detect_autoincrement_missing_keys` | Returns False when column_info is missing identity/default/autoincrement keys |
| `test_pg_reset_autoincrement_cursor_without_fetchall` | Does not crash when cursor has no fetchall attribute |
| `test_pg_bulk_optimizer_preserve_failure_then_restore` | restore uses default values after preserve failure |
| `test_pg_bulk_optimizer_restore_without_preserve` | Does not crash when restore is called without prior preserve |

### 5.6 optimizer.py migration to BulkWriteOptimizer abstraction

**File:** `tests/test_database/test_optimizer.py` (extended)
**Test count:** ~4

| Test | Description |
|------|-------------|
| `test_pragma_optimizer_via_sqlite_bulk_optimizer` | Call PragmaOptimizer through SQLiteBulkOptimizer |
| `test_bulk_optimizer_protocol_satisfied` | PragmaOptimizer satisfies BulkWriteOptimizer protocol (if applicable) |
| `test_sqlite_bulk_optimizer_three_tiers` | Three optimization tiers (light/moderate/aggressive) through abstraction layer |
| `test_sqlite_bulk_optimizer_restore_after_optimize` | restore recovers original values after optimize |

### 5.7 MCP server complete tool tests

**File:** `plugins/mcp-server-sqlseed/tests/test_server.py` (new)
**Class:** `TestMCPTools`
**Test count:** ~12

| Test | Description |
|------|-------------|
| `test_sqlseed_inspect_schema_sqlite` | inspect_schema tool returns correct schema |
| `test_sqlseed_inspect_schema_pg` | inspect_schema tool with PG URL (depends on pg_url) |
| `test_sqlseed_generate_yaml_sqlite` | generate_yaml tool returns valid YAML |
| `test_sqlseed_execute_fill_sqlite` | execute_fill tool actually writes data |
| `test_sqlseed_execute_fill_count_correct` | Row count correct after execute_fill |
| `test_sqlseed_gemma4_analyze_real_llm` | gemma4_analyze real LLM call (depends on available_llm_backend) |
| `test_sqlseed_gemma4_agent_fill_real_llm` | gemma4_agent_fill real LLM call |
| `test_sqlseed_list_gemma_models` | list_gemma_models returns model list |
| `test_get_schema_resource` | get_schema_resource resource returns schema |
| `test_tool_invalid_db_path_raises` | Tool reports error correctly when given invalid path |
| `test_tool_nonexistent_table_raises` | Tool reports error correctly when given non-existent table |
| `test_tool_url_passes_through` | Tool correctly passes URL to orchestrator |

**CP3 total: ~48 tests**

## 6. Dependency Preparation and Environment Configuration

### 6.1 New Test Dependencies

**File:** `pyproject.toml` `[project.optional-dependencies] dev`

Add:
- `testcontainers>=4.0` — real PG integration tests
- `psycopg[binary]>=3.0` — PG driver (required for integration tests)

### 6.2 pytest Configuration

**File:** `pyproject.toml` `[tool.pytest.ini_options]`

```toml
markers = [
    "integration: requires external services (Docker for PG, LLM backend)",
]
# Note: -m "not integration" is NOT configured; integration tests run by default
# When Docker/LLM is missing, fail with prompt rather than skip
```

### 6.3 PG Integration Test Fixture

**File:** `tests/integration/conftest.py`

```python
@pytest.fixture(scope="session")
def pg_url() -> str:
    """Start a real PG container, return connection URL. Fail with prompt when Docker is missing."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.fail(
            "testcontainers package is required to run PG integration tests. "
            "Install: pip install testcontainers"
        )
    try:
        pg = PostgresContainer("postgres:16-alpine")
        pg.start()
        yield pg.get_connection_url()
        pg.stop()
    except Exception as e:
        if "docker" in str(e).lower() or "connection" in str(e).lower():
            pytest.fail(
                "Docker must be running to run PostgreSQL integration tests.\n"
                "Installation guide: https://docs.docker.com/get-docker/\n"
                f"Error details: {e}"
            )
        raise
```

### 6.4 LLM Backend Detection Fixture

**File:** `tests/integration/conftest.py`

```python
@pytest.fixture(scope="session")
def available_llm_backend() -> dict:
    """Detect available LLM backend; fail with prompt when none available.
    Returns {"backend": ..., "model": ...}, where model is the Gemma 4 model ID for that backend.

    Fallback chain: Ollama → LM Studio → Google AI Studio
    """
    import urllib.request

    # 1. Ollama — detect /api/tags, verify gemma4 model is pulled
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as resp:
            tags = json.loads(resp.read())
            models = {m.get("name", "") for m in tags.get("models", [])}
            # Prefer gemma4:26b (recommended), fallback gemma4:e4b (lightweight)
            for preferred in ("gemma4:26b", "gemma4:31b", "gemma4:e4b", "gemma4:12b"):
                if any(m.startswith(preferred) for m in models):
                    return {"backend": "ollama", "model": preferred}
            pytest.fail(
                "Ollama is running but Gemma 4 model is not pulled. Please run:\n"
                "  ollama pull gemma4:26b   # recommended (requires 16GB VRAM)\n"
                "  ollama pull gemma4:e4b   # lightweight alternative (requires 4GB RAM)"
            )
    except Exception:
        pass

    # 2. LM Studio — detect /v1/models, verify gemma-4 model is loaded
    try:
        with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=2) as resp:
            data = json.loads(resp.read())
            model_ids = {m.get("id", "") for m in data.get("data", [])}
            for preferred in ("google/gemma-4-26b-a4b", "google/gemma-4-31b", "google/gemma-4-e4b"):
                if preferred in model_ids:
                    return {"backend": "lm_studio", "model": preferred}
            pytest.fail(
                "LM Studio is running but Gemma 4 model is not loaded. Please load in LM Studio:\n"
                "  google/gemma-4-26b-a4b   # recommended\n"
                "  google/gemma-4-e4b       # lightweight alternative"
            )
    except Exception:
        pass

    # 3. Google AI Studio — detect environment variable
    if os.environ.get("GOOGLE_API_KEY"):
        return {"backend": "google_ai", "model": "gemma-4-26b-a4b-it"}

    pytest.fail(
        "At least one LLM backend is required to run AI integration tests:\n"
        "  - Ollama: install (https://ollama.ai) and pull Gemma 4 model:\n"
        "      ollama pull gemma4:26b   # recommended (requires 16GB VRAM)\n"
        "      ollama pull gemma4:e4b   # lightweight alternative (requires 4GB RAM)\n"
        "  - LM Studio: install and load Gemma 4 model (google/gemma-4-26b-a4b)\n"
        "  - Google AI Studio: set GOOGLE_API_KEY environment variable\n"
        "    (model: gemma-4-26b-a4b-it)"
    )
```

### 6.5 Test Environment Setup Guide

**Required:**
1. **Docker** — PG integration test dependency
   - Install: https://docs.docker.com/get-docker/
   - Verify: `docker run hello-world`

2. **Python dependencies** — `pip install -e ".[dev,all]"` (includes testcontainers, psycopg)

**AI tests (choose one of three):**
1. **Ollama** (recommended, local offline)
   - Install: https://ollama.ai
   - Pull model: `ollama pull gemma4:26b` (recommended, requires 16GB VRAM)
   - Lightweight alternative: `ollama pull gemma4:e4b` (requires 4GB RAM)
   - Verify: `curl http://localhost:11434/api/tags`

2. **LM Studio** (local GUI)
   - Install: https://lmstudio.ai
   - Load model: `google/gemma-4-26b-a4b`
   - Enable local API service (default port 1234)

3. **Google AI Studio** (cloud)
   - Get API Key: https://aistudio.google.com/apikey
   - Set environment variable: `set GOOGLE_API_KEY=your_key_here`

## 7. MCP server Responsibility Boundary (Confirmed)

Investigation confirms the current MCP server responsibility boundary **already aligns** with the "focus on data generation, database handling by specialized MCP" positioning:

### 7.1 Current 6 tools + 1 resource responsibilities

| Tool/Resource | Responsibility | Overlap with Specialized DB MCP |
|---------------|----------------|----------------------------------|
| `sqlseed_execute_fill` | Batch generate test data (core) | Light (INSERT only) |
| `sqlseed_generate_yaml` | AI generates sqlseed-specific YAML | None |
| `sqlseed_gemma4_analyze` | Gemma 4 single-shot analysis | None |
| `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow | None |
| `sqlseed_list_gemma_models` | Gemma 4 model management | None |
| `sqlseed_inspect_schema` | Data generation-specific schema context | Light (but contains schema_hash/sample_data and other dedicated fields) |
| `get_schema_resource` | Same as above, in resource form | Same as above |

### 7.2 Good Boundaries (Already in Place)

- **Zero DDL**: No create/drop/alter table, index, or sequence management
- **Zero database administration**: No backup/migration/user/permission
- **Zero generic SQL execution**: `DataOrchestrator.execute()` not exposed to MCP
- **Thin layer design**: server.py only does parameter validation + delegation

### 7.3 Test Scope Decision

Based on investigation, **fully test the existing 6 tools + 1 resource** (including real LLM calls), without adjusting the responsibility boundary.

## 8. Validation Threshold and Merge Process

### 8.1 Validation Process for Each Checkpoint

1. Write all tests for the checkpoint
2. Run `ruff check src plugins tests` — must have 0 errors
3. Run `ruff format --check src plugins tests` — must have 0 errors
4. Run `mypy src plugins` — must have 0 errors
5. Run `python -m pytest --tb=short -q` — must **all pass** (including new tests + 720 existing tests)
6. Commit the checkpoint's code (conventional commit message)
7. Proceed to next checkpoint

### 8.2 Merge Threshold

- CP1 + CP2 + CP3 all completed
- All ~156 new tests + 720 existing tests pass
- ruff + mypy all pass
- **Merge to main only after explicit user confirmation**

### 8.3 Merge Method

The user decides the merge method (merge commit / squash merge / rebase); AI does not perform automatic merging.

## 9. Risks and Mitigation

| Risk | Mitigation |
|------|------------|
| testcontainers unstable on Windows | Use `postgres:16-alpine` lightweight image; verify in CI |
| LLM call timeout or unstable responses | Set reasonable timeouts; retry mechanism; clear prompts on failure |
| Real PG container slow to start | Session-level fixture; all PG tests share one container |
| Gemma 4 model response quality varies | Validate structure rather than exact content; allow YAML format flexibility |
| Test dependencies increase install time | testcontainers/psycopg only in dev extras; does not affect production |

## 10. Summary

| Checkpoint | Test Count | New Files | Extended Files | Validation Threshold |
|------------|------------|-----------|----------------|----------------------|
| **CP1 (P0)** | ~60 | 4 | 3 | Full pytest passes |
| **CP2 (P1)** | ~48 | 2 | 5 | Full pytest passes |
| **CP3 (P2)** | ~48 | 2 | 3 | Full pytest passes |
| **Total** | **~156** | 8 | 11 | All pass before merge + user confirmation |

**Real environment dependencies:**
- Docker (testcontainers PG integration) — fail if missing
- LLM backend (Ollama/LM Studio/Google AI Studio, Gemma 4 model) — fail if all missing

**Merge threshold:**
- All 156 new tests + 720 existing tests pass
- ruff + mypy all pass
- **Merge only after explicit user confirmation**
