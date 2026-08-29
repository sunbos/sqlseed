<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-08-30 -->

# test_generators

## Purpose

Data generator correctness and consistency tests. Covers Base/Faker/Mimesis providers, registry, dispatch sync, and helper utilities. 8 files, 168 test functions (36 shared in `_mixin.py`).

## Key Files

| File | Tests | Description |
|------|------:|-------------|
| `_mixin.py` | 36 | Shared Provider test mixin |
| `test_string_helpers.py` | 40 | random string utilities |
| `test_json_helpers.py` | 38 | JSON schema generation |
| `test_registry.py` | 17 | ProviderRegistry discovery |
| `test_base_provider.py` | 13 | BaseProvider 35 generators |
| `test_faker_provider.py` | 10 | FakerProvider (required dep) |
| `test_mimesis_provider.py` | 6 | MimesisProvider (optional dep) |
| `test_dispatch_exclude.py` | 7 | `exclude_values` in dispatch |
| `test_dispatch_sync.py` | 1 | `verify_dispatch_sync()` |

## For AI Agents

### Working In This Directory

- `_mixin.py` provides shared Provider test methods to avoid duplication
- `test_registry.py` uses `pytest.importorskip("faker")` / `pytest.importorskip("mimesis")` to guard optional-dep provider discovery; the dedicated provider test files import directly
- Generator tests must verify seed reproducibility
- Dispatch sync tests ensure `GENERATOR_MAP` consistency across providers

### Testing Requirements

```bash
pytest tests/test_generators/
```

### Common Patterns

- Use `_mixin.py` mixin to avoid duplicating test logic
- `test_registry.py` guards optional deps with `pytest.importorskip("faker")` / `pytest.importorskip("mimesis")`; provider test files import directly (faker is required, mimesis is optional)

## Dependencies

### Internal

- `src/sqlseed/generators/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
