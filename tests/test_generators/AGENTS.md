<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-07-12 -->

# test_generators

## Purpose

Data generator correctness and consistency tests. Covers Base/Faker/Mimesis providers, registry, dispatch sync, and helper utilities.

## Key Files

| File | Description |
|------|-------------|
| `_mixin.py` | Shared test mixin, extracts common Provider test logic |
| `test_base_provider.py` | BaseProvider built-in generator tests |
| `test_faker_provider.py` | FakerProvider tests (faker is a required dep; no importorskip) |
| `test_mimesis_provider.py` | MimesisProvider tests (direct import; mimesis optional at runtime) |
| `test_registry.py` | ProviderRegistry registration and discovery tests |
| `test_dispatch_sync.py` | `verify_dispatch_sync()` mapping consistency tests |
| `test_dispatch_exclude.py` | `exclude_values` support in `GeneratorDispatchMixin.generate` tests |
| `test_json_helpers.py` | JSON schema-based generation helper tests |
| `test_string_helpers.py` | Random string utility tests |

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
