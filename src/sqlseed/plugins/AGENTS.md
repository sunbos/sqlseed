# pluggy 基础设施

本目录只定义 hook contract 与插件生命周期；具体 CLI、AI、MCP、Web 实现在仓库 `plugins/`，通用运行时 mediation 在 [../core/plugin_mediator.py](../core/plugin_mediator.py)。

## 入口与边界

- [hookspecs.py](hookspecs.py)：`SqlseedHookSpec`、`hookspec`、`hookimpl`；保留 `PROJECT_NAME = "sqlseed"` namespace。
- [manager.py](manager.py)：`PluginManager` 包装 pluggy；通过 `load_setuptools_entrypoints(PROJECT_NAME)` 自动发现插件，支持显式注册/注销。
- 新 hook 先定义 specs 与调用时机，再更新实现和兼容测试；现有签名属于跨包契约，不能单改调用方。
- 基础设施不导入具体插件；框架日志使用 `_utils.logger`。

## 返回值与调用约定

- `firstresult=True` 返回第一个非 `None` 结果；当前用于 `sqlseed_ai_analyze_table`、`sqlseed_apply_ai_suggestions`、`sqlseed_pre_generate_templates`。
- 其他 hook 返回 `list[result]`，不要按单个 mapping 或单个 batch 处理。
- `PluginMediator.apply_batch_transforms()` 取结果列表中最后一个非 `None` 结果，全部为 `None` 则保留输入 batch。各插件收到同一个 batch 参数；当前实现不把上个返回值作为下个入参，也不累加结果。
- `sqlseed_transform_row` 当前仅有 hookspec，普通 Core 生成流程不调用；不要把声明或插件实现当作已接入的热路径。插件批次变换使用 `sqlseed_transform_batch`；用户配置脚本的 `transform_row(row, ctx)` 是另一条已执行接口。
- `sqlseed_register_providers` / `sqlseed_register_column_mappers` 在连接初始化调用；避免要求每批重新注册。
- `sqlseed_before_generate` / `sqlseed_after_generate` 围绕生成；`sqlseed_before_insert` / `sqlseed_after_insert` 围绕 batch 写入；`sqlseed_shared_pool_loaded` 在 shared pool 注册后调用。
- AI-specific suggestion 实现留在 `sqlseed-ai`；core 只用 hookspec，`PluginMediator` 保持 batch transform / template pool 通用职责。

## 验证与同步

命令从仓库根执行。

- `pytest tests/test_plugins/ tests/test_core/test_plugin_mediator.py`：用真实 pluggy 检查注册、发现、返回值及 mediator。
- hookspec 修改同步 [docs/guide.md](../../../docs/guide.md#plugin-system)、CLAUDE 与两种语言 [docs/architecture.md](../../../docs/architecture.md) 的 hook 参考；本文件的返回值列表也需核对。
- 执行 `python scripts/sync_docs.py`、`pytest tests/test_doc_sync.py tests/test_architecture.py`，不要手改 AUTO-GENERATED count markers。
