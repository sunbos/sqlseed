# AGENTS.md — src/sqlseed/config

## 作用域

- 本目录拥有配置模型、YAML/JSON 加载保存、模板生成，以及 snapshot/replay 的序列化边界。

## 本目录规则

- `models.py` 里的字段名、默认值、validator 和枚举值都属于外部契约；改动前先看 `tests/test_config/`、`tests/test_public_api.py` 和 README 示例。
- `ColumnConfig` 的两种模式要继续由模型层兜底校验：`generator` / `params` 路径与 `derive_from` / `expression` 路径互斥，不要把这类校验下沉到 CLI 或 orchestrator。
- `load_config()` / `save_config()` 只接受 `.yaml`、`.yml`、`.json`；保持 UTF-8、`allow_unicode=True` 和当前字段顺序友好输出。
- `generate_template()` 与 `SnapshotManager` 是 CLI `sqlseed init` / `sqlseed replay` 的配置边界。输出 shape、默认值或文件命名变化要同步更新 CLI 测试和文档。
- 快照内容来自 `config.model_dump(mode="json")`；不要往配置模型里塞不可序列化对象、数据库句柄或运行时回调。
- 本目录负责 schema 与 serialization，不负责数据库 I/O，也不要反向依赖可选插件实现包。

## 评审热点

- `models.py` 的字段兼容性会直接影响 YAML/JSON 配置、Python API 和 AI/MCP 侧生成的配置。
- `loader.py` 的扩展名分支和错误消息是用户入口，改动时留意 `tests/test_config/test_loader.py`。
- `snapshot.py` 会把配置重新喂回 `DataOrchestrator.from_config()`；如果回放漏传字段，容易只在集成测试里暴露。

## 验证

- 配置层：`pytest tests/test_config`
- 关联入口：`pytest tests/test_public_api.py tests/test_cli.py`
