# DATA GENERATORS LAYER

**Last updated:** 2026-08-23

## OVERVIEW

35 generators across 3 providers: base (zero-dep fallback, synthesizes values via counter + seeded RNG), faker (required), mimesis (optional).

## STRUCTURE

```
generators/
├── __init__.py           # Public API exports
├── _protocol.py         # DataProvider protocol + UnknownGeneratorError
├── _dispatch.py         # GeneratorDispatchMixin — 35 generator dispatch + verify_dispatch_sync()
├── _json_helpers.py     # JSON schema-based generation
├── _string_helpers.py   # Random string utilities
├── registry.py          # ProviderRegistry — entry-point discovery
├── base_provider.py     # BaseProvider — zero-dep fallback; synthesizes placeholder data via counter + seeded RNG (no hardcoded lists)
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
- **Phone**: locale-real format by default (faker/mimesis native); explicit `mask` param forces a unified custom format across providers
- **Faker locale probing**: at init, per-instance probe for locale-missing methods (zh_CN lacks `state()`/`zipcode()`) and install BaseProvider fallbacks; cleared on locale switch back — never crash mid-fill

## ANTI-PATTERNS

- **NEVER** import optional third-party libs without a guard → rstr is imported unconditionally at module top; faker is imported at module top via ``importlib.import_module("faker")`` + try/except (``HAS_FAKER`` guard); only mimesis may use function-level lazy import.
- **NEVER** raise in generate() without UnknownGeneratorError
- **ALWAYS** implement all 35 generators or handle gracefully
- **ALWAYS** use `self._rng` for random (seed support)
