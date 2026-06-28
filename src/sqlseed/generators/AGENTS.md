# DATA GENERATORS LAYER

**Generated:** 2026-06-21

## OVERVIEW

31 generators across 3 providers: base (type-routing only, no real data), faker (required), mimesis (optional).

## STRUCTURE

```
generators/
├── __init__.py           # Public API exports
├── _protocol.py         # DataProvider protocol + UnknownGeneratorError
├── _dispatch.py         # GeneratorDispatchMixin — 31 generator dispatch + verify_dispatch_sync()
├── _json_helpers.py     # JSON schema-based generation
├── _string_helpers.py   # Random string utilities
├── registry.py          # ProviderRegistry — entry-point discovery
├── base_provider.py     # BaseProvider — type-routing only (no real data generation); delegates to faker/mimesis
├── faker_provider.py    # FakerProvider — faker adapter
└── mimesis_provider.py  # MimesisProvider — mimesis adapter
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add generator | `base_provider.py` | Add `_gen_<name>()` method |
| Add provider | New file | Implement DataProvider protocol |
| Register provider | `registry.py` | Entry-point or plugin hook |
| Modify dispatch | `_dispatch.py` | GeneratorDispatchMixin.generate(), verify_dispatch_sync() |
| Add JSON type | `_json_helpers.py` | generate_json_from_schema() |

## CONVENTIONS

- **Provider protocol**: Implement `name`, `set_locale()`, `set_seed()`, `generate()`
- **Generator naming**: `_gen_<type_name>()` methods in provider
- **Entry points**: Register in `pyproject.toml` `[project.entry-points."sqlseed"]`
- **Fallback chain**: mimesis → faker → base (auto-degrades)
- **Locale support**: `set_locale()` called before generation

## ANTI-PATTERNS

- **NEVER** import mimesis at module top → use try/except (lazy import). faker and rstr are required deps, import at module top.
- **NEVER** raise in generate() without UnknownGeneratorError
- **ALWAYS** implement all 31 generators or handle gracefully
- **ALWAYS** use `self._rng` for random (seed support)
