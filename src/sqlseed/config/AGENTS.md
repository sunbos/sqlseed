# 配置与 snapshot

**核验日期：** 2026-09-14

本目录负责 YAML/JSON loading、Pydantic models、离线模板和配置快照，承接[核心包规则](../AGENTS.md)。配置驱动的执行留在 orchestrator；CLI replay 留在 CLI plugin。

## 入口

- [models.py](models.py)：`GeneratorConfig`、`TableConfig`、`ColumnConfig`、constraints、associations、自定义 mapping rules。
- [loader.py](loader.py)：`load_config()`、`save_config()`、`generate_template()`；SQLAlchemy 是直接导入的必需依赖，table discovery 创建的 engine 在 `finally` 中 dispose。
- [snapshot.py](snapshot.py)：`SnapshotManager.save/load/list_snapshots`；不要添加执行生成逻辑。

## 不变量

- `GeneratorConfig.db_path` 与 `url` 必须二选一；统一经 `connection_target` 取连接目标。
- `ColumnConfig.generator` 与 `derive_from` 互斥；存在 `derive_from` 必须有 `expression`。保留 validator，不能仅依靠调用方清理。
- Source mode 使用 `generator/params/provider/null_ratio`；derived mode 使用 `derive_from/expression`，不要在 derived 配置中混入 source generator。
- `normalize_dict_input()` 将 `type` 作为 `generator` alias，两者同时存在时保留 `generator` 并 warning；非 derived 的未知字段合入 `params`，顶层额外参数覆盖 nested params。
- normalization 复制输入，不原地修改调用方字典；source `params=None` 与空 mapping 保持兼容，非 mapping 值明确拒绝，不能静默丢弃用户参数。derived 输入不进行 source params 平铺。
- 无装饰器的 `normalize_column_input()` 共用于 model validator 与插件参数修复；保持传入模型字段集合，避免子类字段误入 `params`，不要在插件复制别名/平铺规则。
- `_degraded`、`degrade_reason` 是内部 metadata，不能进入 generator params，否则会造成意外 keyword 参数错误。
- `ColumnConstraintsConfig.max_retries >= 0`，`null_ratio` 范围为 `[0, 1]`；`TableConfig.count/batch_size` 必须为正。
- 保留 `faker_method`、`mimesis_method`、`native_params` 的 native override 配置传递。
- `ProviderType` 值为 base/faker/mimesis/custom；新增选择时核对 registry 与调用方，不仅修改 enum。
- `ColumnAssociation` 是独立跨表模型：`column_name/source_table/source_column/target_tables/strategy`；未给 `source_column` 时由关系层回退到 `column_name`。
- `custom_column_mappings` 包含 exact 与 pattern 规则，优先级由 `ColumnMapper` 执行。
- 新字段给出兼容默认值，保留既有配置加载；`log_level` 已 deprecated，仅兼容读取，不再应用配置值。

## 读写与模板

- `load_config()` 按大小写无关的 `.yaml/.yml/.json` 后缀选 parser，顶层必须为 mapping；不要把空文档或列表当成空配置。
- `save_config()` 在创建目录或打开目标前完成后缀校验、JSON-mode dump、序列化与 UTF-8 编码；格式或编码失败必须保留旧文件。此保障不等于原子替换或所有 I/O 故障均可回滚。
- `generate_template(table_name=...)` 不读取数据库；未指定表时才发现用户表并过滤 SQLite 系统表。发现失败只记录 warning 并返回空表模板，不代表已经验证数据库可执行。

## 快照

- `SnapshotManager` 使用 `get_cache_dir("snapshots")` 或显式目录，以含微秒的 timestamp 命名避免同秒冲突。
- 快照文件名不得直接使用任意 SQL 表名；特殊或过长名称使用安全摘要，原名保留在内容中。`load()` 对非 mapping 内容抛出 `ValueError`。
- snapshot 外层保存 timestamp/table_name/count/seed，配置通过 `model_dump(mode="json")` 序列化；`load()` 返回外层字典，不是 `GeneratorConfig`。
- CLI replay 使用 `load()` 加 `DataOrchestrator.from_config()`；不要重新添加 `SnapshotManager.replay()`。

## 验证与同步

从仓库根执行 `pytest tests/test_config/`；normalization/保存边界重点看 `test_normalization_and_save_regressions.py`，snapshot 重点看 `test_snapshot.py`。修改 models 后同步 [docs/architecture.md](../../../docs/architecture.md) 与 [docs/architecture.zh-CN.md](../../../docs/architecture.zh-CN.md) 的字段与 class diagrams，并运行 `pytest tests/test_doc_sync.py`。配置使用说明承接 [docs/guide.md](../../../docs/guide.md)。
