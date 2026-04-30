# TEST SUITE

## OVERVIEW

pytest suite. Tests mirror `src/sqlseed/` structure. conftest.py provides fixtures.

## STRUCTURE

```
tests/
├── conftest.py              # Fixtures: tmp_db, tmp_db_with_data, bank_cards_db
├── _helpers.py              # Test utilities
├── test_public_api.py       # Public API tests (fill, connect, preview)
├── test_orchestrator.py     # DataOrchestrator tests
├── test_mapper.py           # ColumnMapper tests
├── test_schema.py           # SchemaInferrer tests
├── test_relation.py         # RelationResolver tests
├── test_result.py           # GenerationResult tests
├── test_refiner.py          # AI refiner tests
├── test_enrich_enum_detection.py  # Enrichment tests
├── test_cli.py              # CLI tests
├── test_cli_yaml_priority.py    # CLI YAML priority tests
├── test_ai_plugin.py        # AI plugin integration tests (531 lines)
├── test_core/               # Core module tests
├── test_generators/         # Generator tests
├── test_database/           # Database adapter tests
├── test_config/             # Config tests
├── test_plugins/            # Plugin tests
├── test_utils/              # Utility tests
└── benchmarks/              # Performance benchmarks
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add fixture | `conftest.py` | tmp_db, tmp_db_with_data, bank_cards_db |
| Test new generator | `test_generators/` | Mirror generators/ structure |
| Test core logic | `test_core/` | Mirror core/ structure |
| Test CLI | `test_cli.py` | Click CliRunner |
| Test AI plugin | `test_ai_plugin.py` | Integration tests |
| Add benchmark | `benchmarks/` | pytest-benchmark |

## CONVENTIONS

- **Naming**: `test_<module>.py` mirrors `src/sqlseed/<module>/`
- **Fixtures**: Use `tmp_db`, `tmp_db_with_data`, `bank_cards_db` from conftest
- **DB creation**: Use `create_simple_db()`, `create_card_info_db()` helpers
- **Orchestrator tests**: Use `DataOrchestrator` as context manager
- **Type hints**: Relaxed in tests (mypy overrides in pyproject.toml)

## ANTI-PATTERNS

- **NEVER** hardcode DB paths → use `tmp_path` fixture
- **NEVER** skip cleanup → use context managers or fixtures
- **ALWAYS** use `provider="base"` in tests (no external deps)
- **ALWAYS** use `gc.collect()` between tests (autouse fixture)
