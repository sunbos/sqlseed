<!-- Parent: ../AGENTS.md -->

# config

**Last updated:** 2026-07-12

## Purpose

Loading, validation, and model definitions for YAML/JSON configuration files. Builds type-safe configuration models on top of Pydantic.

## Key Files

| File | Description |
|------|-------------|
| `models.py` | Pydantic configuration models: `GeneratorConfig`, `TableConfig`, `ColumnConfig`, `ColumnConstraintsConfig`, `ProviderType` |
| `loader.py` | Configuration file loader supporting YAML and JSON formats, with template generation (supports multi-database URLs) |
| `snapshot.py` | `SnapshotManager` for saving and loading configuration snapshots (save/load/list_snapshots; replay has been removed) |
| `__init__.py` | Public API exports |

## For AI Agents

### Working In This Directory

- Source-column mode (`generator` + `params`) and derived-column mode (`derive_from` + `expression`) are mutually exclusive, enforced via `model_validator`; do not break this constraint
- The `ProviderType` enum has four values: BASE/FAKER/MIMESIS/CUSTOM
- Modifications to Pydantic models must remain backward compatible; existing configuration files should not fail to load due to model changes
- `field_validator`/`model_validator` are the core validation logic; when modifying them, ensure all constraints are still satisfied
- New configuration options should provide sensible defaults to avoid breaking existing user configurations
- `ColumnAssociation` is an independent cross-table association model (not an enum inside `ColumnConfig`); fields: `column_name`, `source_table`, `source_column` (defaults to None, falls back to column_name), `target_tables`, `strategy="shared_pool"`

### Testing Requirements

```bash
pytest tests/test_config/
```

### Common Patterns

- Model hierarchy: `GeneratorConfig` → `TableConfig` → `ColumnConfig` → `ColumnConstraintsConfig`
- `SnapshotManager` names snapshot files by timestamp
- Configuration templates are generated via `generate_template()` in `loader.py`
- `url` provides multi-database support (mutually exclusive with db_path): `GeneratorConfig` specifies the connection target via either `db_path` or `url`; the two are mutually exclusive
- The `connection_target` property returns the connection target (url or db_path)
- `generate_template` supports URLs (uses SQLAlchemy to read table names, imported lazily to avoid circular dependencies)

## Dependencies

### Internal

- `_utils` (logger)
- `paths` (snapshot.py uses get_cache_dir)

### External

- `pydantic>=2.0` — model definition and validation
- `pyyaml>=6.0` — YAML loading
- `typing_extensions` — `Self` type (model_validator return type)
- `sqlalchemy` — loader.py reads table names (imported lazily)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
