# AGENTS.md — src/sqlseed/plugins

## 作用域

- 本目录拥有 `pluggy` hook 规范与 `PluginManager`，负责核心包和外部插件之间的协议边界。

## 文件清单

| 文件 | 职责 |
|------|------|
| `hookspecs.py` | `SqlseedHookSpec`（11 个 Hook 规范）、`hookspec`/`hookimpl` 标记、`PROJECT_NAME = "sqlseed"` |
| `manager.py` | `PluginManager`（pluggy 封装：注册、发现、分发） |

## 本目录规则

- `hookspecs.py` 是外部插件契约。hook 名称、参数名、`firstresult` 语义和项目名 `sqlseed` 都不要轻易改。
- `PluginManager` 只负责规范注册、entry point 发现和 hook 分发；不要把 AI、MCP 或具体业务逻辑塞进这里。
- entry point group 固定为 `[project.entry-points."sqlseed"]`。如果发现加载失败，优先保持软失败和可诊断日志，而不是让主流程初始化直接崩掉。
- 新增 hook 前先确认现有 hook 是否已足够表达需求，并同步补 `tests/test_plugins/test_hookspecs.py`、`tests/test_plugins/test_manager.py` 以及调用方测试。
- hook payload 应尽量传稳定、可序列化或容易理解的数据形状；不要把临时内部对象暴露成第三方插件必须依赖的实现细节。
- `sqlseed_transform_row` 被标注为 "hot path - performance sensitive"，提醒实现者注意性能。
- `sqlseed_transform_batch` 的文档注释说明 "Multiple plugins can chain: each plugin's output feeds into the next"。

## 11 个 Hook 规范详情

| # | Hook 名称 | firstresult | 签名 |
|---|-----------|-------------|------|
| 1 | `sqlseed_register_providers` | 否 | `(self, registry: Any) -> None` |
| 2 | `sqlseed_register_column_mappers` | 否 | `(self, mapper: Any) -> None` |
| 3 | `sqlseed_ai_analyze_table` | **是** | `(self, table_name, columns, indexes, sample_data, foreign_keys, all_table_names) -> dict \| None` |
| 4 | `sqlseed_before_generate` | 否 | `(self, table_name, count, config) -> None` |
| 5 | `sqlseed_after_generate` | 否 | `(self, table_name, count, elapsed) -> None` |
| 6 | `sqlseed_transform_row` | 否 | `(self, table_name, row) -> dict \| None` |
| 7 | `sqlseed_transform_batch` | 否 | `(self, table_name, batch) -> list \| None` |
| 8 | `sqlseed_before_insert` | 否 | `(self, table_name, batch_number, batch_size) -> None` |
| 9 | `sqlseed_after_insert` | 否 | `(self, table_name, batch_number, rows_inserted) -> None` |
| 10 | `sqlseed_shared_pool_loaded` | 否 | `(self, table_name, shared_pool) -> None` |
| 11 | `sqlseed_pre_generate_templates` | **是** | `(self, table_name, column_name, column_type, count, sample_data) -> list \| None` |

## 评审热点

- `firstresult=True` 的 hook（`sqlseed_ai_analyze_table` 和 `sqlseed_pre_generate_templates`）会影响短路行为；改错一个标记就可能改变 AI 建议或模板池的优先级。
- manager 的 entry point 发现会同时看到 Provider 和插件包；日志粒度过高或异常处理过硬都会放大可选依赖问题。
- 调整 hook 规范时要联动 `plugins/sqlseed-ai/`、`plugins/mcp-server-sqlseed/` 以及顶层插件测试。

## 验证

- 插件层：`pytest tests/test_plugins`
- 关联集成：`pytest tests/test_ai_plugin.py tests/test_cli.py`
