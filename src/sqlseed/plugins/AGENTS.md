# AGENTS.md — src/sqlseed/plugins

## 作用域

- 本目录拥有 `pluggy` hook 规范与 `PluginManager`，负责核心包和外部插件之间的协议边界。

## 本目录规则

- `hookspecs.py` 是外部插件契约。hook 名称、参数名、`firstresult` 语义和项目名 `sqlseed` 都不要轻易改。
- `PluginManager` 只负责规范注册、entry point 发现和 hook 分发；不要把 AI、MCP 或具体业务逻辑塞进这里。
- entry point group 固定为 `[project.entry-points."sqlseed"]`。如果发现加载失败，优先保持软失败和可诊断日志，而不是让主流程初始化直接崩掉。
- 新增 hook 前先确认现有 hook 是否已足够表达需求，并同步补 `tests/test_plugins/test_hookspecs.py`、`tests/test_plugins/test_manager.py` 以及调用方测试。
- hook payload 应尽量传稳定、可序列化或容易理解的数据形状；不要把临时内部对象暴露成第三方插件必须依赖的实现细节。

## 评审热点

- `firstresult=True` 的 hook 会影响短路行为；改错一个标记就可能改变 AI 建议或模板池的优先级。
- manager 的 entry point 发现会同时看到 Provider 和插件包；日志粒度过高或异常处理过硬都会放大可选依赖问题。
- 调整 hook 规范时要联动 `plugins/sqlseed-ai/`、`plugins/mcp-server-sqlseed/` 以及顶层插件测试。

## 验证

- 插件层：`pytest tests/test_plugins`
- 关联集成：`pytest tests/test_ai_plugin.py tests/test_cli.py`
