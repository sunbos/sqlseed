# TEST SUITE

**Last updated:** 2026-08-30

## OVERVIEW

pytest suite. Tests mirror `src/sqlseed/` structure. conftest.py provides fixtures. Root level: 16 test files, 319 test functions. Subdirs: test_core 14 files / 247 tests, test_database 10 files / 265, test_config 3 / 39, test_generators 8 / 168 (incl. `_mixin.py` 36 shared), test_utils 4 / 99, test_plugins 2 / 21, benchmarks 1 / 3.

## STRUCTURE

```
tests/
├── conftest.py              # Test helpers; fixtures moved to rootdir conftest.py
├── _helpers.py              # Test utilities
├── _ai_helpers.py           # Shared helpers for sqlseed-ai plugin tests
├── test_public_api.py       # 10 tests — fill, connect, preview
├── test_orchestrator.py     # 41 tests — DataOrchestrator
├── test_orchestrator_adapter.py  # 9 tests — orchestrator-adapter integration
├── test_mapper.py           # 33 tests — ColumnMapper
├── test_mapper_camelcase.py # 21 tests — camelCase name mapping
├── test_schema.py           # 16 tests — SchemaInferrer
├── test_relation.py         # 41 tests — RelationResolver
├── test_result.py           # 4 tests — GenerationResult
├── test_enrich_enum_detection.py  # 18 tests — enrichment
├── test_architecture.py     # 14 tests — architecture invariants
├── test_doc_sync.py         # 13 tests — AUTO-GENERATED markers (17 with param)
├── test_hardware.py         # 8 tests — sqlseed_ai._hardware
├── test_refiner.py          # 61 tests — AiConfigRefiner (sqlseed-ai)
├── test_url_connection.py   # 15 tests — --url / _resolve_db_target
├── test_core/               # 14 files, 247 tests
├── test_generators/         # 8 files, 168 tests
├── test_database/           # 10 files, 265 tests
├── test_config/             # 3 files, 39 tests
├── test_plugins/            # 2 files, 21 tests
├── test_utils/              # 4 files, 99 tests
├── integration/             # Integration tests (test_pg_integration.py, test_url_e2e.py, test_ai_real_llm.py)
└── benchmarks/              # bench_fill.py (3 benchmarks)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add fixture | root `conftest.py` (not tests/) | tmp_db, tmp_db_with_data, unique_test_db |
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
