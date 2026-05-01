<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# plugins

## Purpose

基于 pluggy 的插件框架集成。定义 hook 规范和管理插件生命周期。

## Key Files

| File | Description |
|------|-------------|
| `hookspecs.py` | `SqlseedHookSpec` hook 规范定义，`hookspec`/`hookimpl` 标记 |
| `manager.py` | `PluginManager` 封装 pluggy.PluginManager，自动发现和注册插件 |

## Hook 完整列表（11 个）

| # | Hook 名称 | firstresult | 签名 |
|---|-----------|-------------|------|
| 1 | `sqlseed_register_providers` | 否 | `(self, registry: Any) -> None` |
| 2 | `sqlseed_register_column_mappers` | 否 | `(self, mapper: Any) -> None` |
| 3 | `sqlseed_ai_analyze_table` | **是** | `(self, table_name, columns, indexes, sample_data, foreign_keys, all_table_names) -> dict | None` |
| 4 | `sqlseed_before_generate` | 否 | `(self, table_name, count, config) -> None` |
| 5 | `sqlseed_after_generate` | 否 | `(self, table_name, count, elapsed) -> None` |
| 6 | `sqlseed_transform_row` | 否 | `(self, table_name, row) -> dict | None` |
| 7 | `sqlseed_transform_batch` | 否 | `(self, table_name, batch) -> list | None` |
| 8 | `sqlseed_before_insert` | 否 | `(self, table_name, batch_number, batch_size) -> None` |
| 9 | `sqlseed_after_insert` | 否 | `(self, table_name, batch_number, rows_inserted) -> None` |
| 10 | `sqlseed_shared_pool_loaded` | 否 | `(self, table_name, shared_pool) -> None` |
| 11 | `sqlseed_pre_generate_templates` | **是** | `(self, table_name, column_name, column_type, count, sample_data) -> list | None` |

- `sqlseed_transform_row` 标记为 "hot path - performance sensitive"
- `sqlseed_transform_batch` 支持链式应用：每个插件的输出作为下一个插件的输入

## For AI Agents

### Working In This Directory

- 新增 hook 需在 `SqlseedHookSpec` 中定义，并更新 `hookimpl` 标记
- hook 签名变更需考虑已有插件的兼容性，应提供过渡期
- `PROJECT_NAME = "sqlseed"` 是 pluggy 命名空间，不要修改
- 插件通过 `sqlseed` entry_points 自动发现（如 sqlseed-ai 的 `ai = sqlseed_ai:plugin`）

### Testing Requirements

```bash
pytest tests/test_plugins/
```

### Common Patterns

- Hook 规范与实现解耦：`SqlseedHookSpec` 定义接口，插件通过 `@hookimpl` 实现
- `PluginManager` 通过 `importlib.metadata` 扫描 entry_points 自动注册
- `firstresult=True` 的 hook 只取第一个非 None 结果

## Dependencies

### Internal

- 无（框架层，不依赖其他内部模块）

### External

- `pluggy>=1.3` — 插件框架

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
