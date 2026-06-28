<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-06-21 -->

# test_generators

## Purpose

Data generator correctness and consistency tests. Covers Base/Faker/Mimesis providers, registry, dispatch sync, and helper utilities.

## Key Files

| File | Description |
|------|-------------|
| `_mixin.py` | Shared test mixin, extracts common Provider test logic |
| `test_base_provider.py` | BaseProvider built-in generator tests |
| `test_faker_provider.py` | FakerProvider tests (importorskip) |
| `test_mimesis_provider.py` | MimesisProvider tests (importorskip) |
| `test_registry.py` | ProviderRegistry registration and discovery tests |
| `test_dispatch_sync.py` | `verify_dispatch_sync()` mapping consistency tests |
| `test_json_helpers.py` | JSON schema-based generation helper tests |
| `test_string_helpers.py` | Random string utility tests |

## For AI Agents

### Working In This Directory

- `_mixin.py` provides shared Provider test methods to avoid duplication
- Faker/Mimesis tests must use `pytest.importorskip` to handle missing optional dependencies
- Generator tests must verify seed reproducibility
- Dispatch sync tests ensure `_GENERATOR_MAP` consistency across providers

### Testing Requirements

```bash
pytest tests/test_generators/
```

### Common Patterns

- Use `_mixin.py` mixin to avoid duplicating test logic
- Optional dependency tests use `pytest.importorskip("faker")` / `pytest.importorskip("mimesis")`

## Dependencies

### Internal

- `src/sqlseed/generators/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
