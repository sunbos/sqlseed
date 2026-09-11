# test_plugins

本目录验证 core 的 pluggy hook specifications 与 manager lifecycle；不是各业务插件的测试目录。

## 入口与回归要求

- `test_hookspecs.py` 验证 hook 名称、签名与 `firstresult` 元数据；以 `src/sqlseed/plugins/hookspecs.py` 为定义来源。
- `test_manager.py` 验证注册、卸载、分发与生命周期；使用真实 `PluginManager` 和内联 dummy plugin classes。
- 区分 `firstresult=True` 的单值与普通 hook 的 `list[result]`，包含全 None / 多个结果的情况。
- 验证 batch transform 结果处理时，同时参考 `tests/test_core/test_plugin_mediator.py`；不要假设 pluggy 会把一个插件的输出依次传入下一个插件。
- CLI、AI、MCP、Web 的业务行为测试放在各插件自己的 `tests/`，避免这里强制依赖业务插件。

## 验证

从仓库根执行：

```bash
pytest tests/test_plugins/ tests/test_core/test_plugin_mediator.py
pytest tests/test_architecture.py tests/test_doc_sync.py
```

修改 hookspec 时同步根指引列出的 hook 文档；hook 数量由源码与校验维护，不在本文件固定统计。
