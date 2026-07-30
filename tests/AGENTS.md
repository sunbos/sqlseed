# TEST SUITE

## OVERVIEW

pytest suite. Tests mirror `src/sqlseed/` structure. conftest.py provides fixtures.

## STRUCTURE

```
tests/
├── conftest.py              # Test helpers; fixtures moved to rootdir conftest.py
├── _helpers.py              # Test utilities
├── _ai_helpers.py           # Shared helpers for sqlseed-ai plugin tests
├── test_public_api.py       # Public API tests (fill, connect, preview)
├── test_orchestrator.py     # DataOrchestrator tests
├── test_orchestrator_adapter.py  # Orchestrator-adapter integration tests
├── test_mapper.py           # ColumnMapper tests
├── test_mapper_camelcase.py # ColumnMapper camelCase name tests
├── test_schema.py           # SchemaInferrer tests
├── test_relation.py         # RelationResolver tests
├── test_result.py           # GenerationResult tests
├── test_enrich_enum_detection.py  # Enrichment tests
├── test_architecture.py     # Architecture guard tests (14 invariants)
├── test_doc_sync.py         # Doc sync verification (AUTO-GENERATED markers)
├── test_hardware.py         # Hardware detection tests (sqlseed_ai._hardware)
├── test_refiner.py          # AiConfigRefiner tests (sqlseed-ai)
├── test_url_connection.py   # URL connection tests (--url / _resolve_db_target)
├── test_core/               # Core module tests
├── test_generators/         # Generator tests
├── test_database/           # Database adapter tests
├── test_config/             # Config tests
├── test_plugins/            # Plugin tests
├── test_utils/              # Utility tests
├── integration/             # Integration tests (test_pg_integration.py, test_url_e2e.py, test_ai_real_llm.py)
└── benchmarks/              # Performance benchmarks
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add fixture | `conftest.py` | tmp_db, tmp_db_with_data, unique_test_db |
| Test new generator | `test_generators/` | Mirror generators/ structure |
| Test core logic | `test_core/` | Mirror core/ structure |
| Test CLI | `plugins/sqlseed-cli/tests/` | Click CliRunner |
| Test AI plugin | `plugins/sqlseed-ai/tests/` | Integration tests |
| Add benchmark | `benchmarks/` | pytest-benchmark |

## CONVENTIONS

- **Naming**: `test_<module>.py` mirrors `src/sqlseed/<module>/`
- **Fixtures**: Use `tmp_db`, `tmp_db_with_data`, `unique_test_db` from conftest
- **DB creation**: Use `create_simple_db()`, `create_project_info_db()` helpers
- **Orchestrator tests**: Use `DataOrchestrator` as context manager
- **Type hints**: Relaxed in tests (mypy overrides in pyproject.toml)

## ANTI-PATTERNS

- **NEVER** hardcode DB paths → use `tmp_path` fixture
- **NEVER** skip cleanup → use context managers or fixtures
- **ALWAYS** use `provider="base"` in tests (no external deps)
- Use the opt-in `gc_between_tests` fixture for memory-sensitive tests (not autouse)
