<!-- Parent: ../AGENTS.md -->

**Generated:** 2026-06-21

# plugins

## Purpose

pluggy-based plugin framework integration. Defines hook specifications and manages the plugin lifecycle.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Public API exports |
| `hookspecs.py` | `SqlseedHookSpec` hook specification definitions, `hookspec`/`hookimpl` markers |
| `manager.py` | `PluginManager` wraps pluggy.PluginManager, auto-discovers and registers plugins |

## Complete Hook List (12 hooks)

| # | Hook Name | firstresult | Signature |
|---|-----------|-------------|-----------|
| 1 | `sqlseed_register_providers` | No | `(self, registry: Any) -> None` |
| 2 | `sqlseed_register_column_mappers` | No | `(self, mapper: Any) -> None` |
| 3 | `sqlseed_ai_analyze_table` | **Yes** | `(self, table_name, columns, indexes, sample_data, foreign_keys, all_table_names) -> dict | None` |
| 4 | `sqlseed_apply_ai_suggestions` | **Yes** | `(self, table_name, column_infos, specs, user_configured_columns, db, schema) -> dict | None` |
| 5 | `sqlseed_before_generate` | No | `(self, table_name, count, config) -> None` |
| 6 | `sqlseed_after_generate` | No | `(self, table_name, count, elapsed) -> None` |
| 7 | `sqlseed_transform_row` | No | `(self, table_name, row) -> dict | None` |
| 8 | `sqlseed_transform_batch` | No | `(self, table_name, batch) -> list | None` |
| 9 | `sqlseed_before_insert` | No | `(self, table_name, batch_number, batch_size) -> None` |
| 10 | `sqlseed_after_insert` | No | `(self, table_name, batch_number, rows_inserted) -> None` |
| 11 | `sqlseed_shared_pool_loaded` | No | `(self, table_name, shared_pool) -> None` |
| 12 | `sqlseed_pre_generate_templates` | **Yes** | `(self, table_name, column_name, column_type, count, sample_data) -> list | None` |

- `sqlseed_transform_row` is marked as "hot path - performance sensitive"
- `sqlseed_transform_batch` supports chained application: each plugin's output becomes the next plugin's input

## For AI Agents

### Working In This Directory

- New hooks must be defined in `SqlseedHookSpec` and the `hookimpl` marker updated accordingly
- Hook signature changes must consider compatibility with existing plugins; a transition period should be provided
- `PROJECT_NAME = "sqlseed"` is the pluggy namespace; do not modify it
- Plugins are auto-discovered via the `sqlseed` entry_points (e.g. sqlseed-ai's `ai = sqlseed_ai:plugin`)

### Testing Requirements

```bash
pytest tests/test_plugins/
```

### Common Patterns

- Hook specifications are decoupled from implementations: `SqlseedHookSpec` defines the interface, plugins implement it via `@hookimpl`
- `PluginManager` auto-registers by scanning entry_points via `importlib.metadata`
- Hooks with `firstresult=True` only take the first non-None result

## Dependencies

### Internal

- None (framework layer; does not depend on other internal modules)

### External

- `pluggy>=1.3` — Plugin framework

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
