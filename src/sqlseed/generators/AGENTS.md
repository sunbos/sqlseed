# DATA GENERATORS LAYER

## OVERVIEW

31 generators across 3 providers: base (no deps), faker (optional), mimesis (optional).

## STRUCTURE

```
generators/
├── _protocol.py         # DataProvider protocol + UnknownGeneratorError
├── _dispatch.py         # GeneratorDispatchMixin — 31 generator dispatch
├── _json_helpers.py     # JSON schema-based generation
├── _string_helpers.py   # Random string utilities
├── registry.py          # ProviderRegistry — entry-point discovery
├── base_provider.py     # BaseProvider — 31 generators, zero deps (677 lines)
├── faker_provider.py    # FakerProvider — faker adapter
├── mimesis_provider.py  # MimesisProvider — mimesis adapter
└── stream.py            # DataStream — batch generation + constraint backtracking
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add generator | `base_provider.py` | Add `_gen_<name>()` method |
| Add provider | New file | Implement DataProvider protocol |
| Register provider | `registry.py` | Entry-point or plugin hook |
| Modify dispatch | `_dispatch.py` | GeneratorDispatchMixin.generate() |
| Add JSON type | `_json_helpers.py` | generate_json_from_schema() |
| Batch generation | `stream.py` | DataStream.generate() — yields batches |

## CONVENTIONS

- **Provider protocol**: Implement `name`, `set_locale()`, `set_seed()`, `generate()`
- **Generator naming**: `_gen_<type_name>()` methods in provider
- **Entry points**: Register in `pyproject.toml` `[project.entry-points."sqlseed"]`
- **Fallback chain**: mimesis → faker → base (auto-degrades)
- **Locale support**: `set_locale()` called before generation

## ANTI-PATTERNS

- **NEVER** import faker/mimesis at module top → use try/except
- **NEVER** raise in generate() without UnknownGeneratorError
- **ALWAYS** implement all 31 generators or handle gracefully
- **ALWAYS** use `self._rng` for random (seed support)
