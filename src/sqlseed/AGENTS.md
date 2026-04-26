# AGENTS.md — src/sqlseed

## 作用域

- 本目录拥有可导入的 `sqlseed` 主包。
- 修改这里的代码时，默认目标是保持 `import sqlseed` 轻量且稳定，即使可选依赖未安装也不应整体失效。

## 目录导航

- `core/`：主编排链路、列映射、表达式、约束、Transform、Enrichment、Relation、Schema。进入该目录前再读 `core/AGENTS.md`。
- `generators/`：`DataProvider` Protocol、`GeneratorDispatchMixin`、Base/Faker/Mimesis/AI Provider、`ProviderRegistry`、`DataStream`。进入该目录前再读 `generators/AGENTS.md`。
- `database/`：`DatabaseAdapter` Protocol、`BaseSQLiteAdapter` 共享基类、`sqlite-utils`/原生 sqlite3 适配器、PRAGMA 优化。进入该目录前再读 `database/AGENTS.md`。
- `config/`：Pydantic 配置模型（含 `ColumnAssociation` 及 `source_column`）、YAML/JSON 加载、模板生成（`generate_template` 自动读取数据库表名）、快照回放。进入该目录前再读 `config/AGENTS.md`。
- `cli/`：Click 命令层，负责参数解析与输出展示。包含 `fill`、`preview`、`inspect`、`init`、`replay`、`ai-suggest` 六个子命令。默认日志级别 `WARNING`，通过 `SQLSEED_LOG_LEVEL` 环境变量控制。注意：`preview` CLI 命令缺少 `--enrich` 和 `--transform` 选项，但 Python API `sqlseed.preview()` 支持这些参数。
- `plugins/`：hook 规范与 `PluginManager`，不是插件实现目录。进入该目录前再读 `plugins/AGENTS.md`。
- `_utils/`：SQL 安全（`quote_identifier`、`validate_table_name`、`build_insert_sql`）、日志（`configure_logging`、`get_logger`）、进度（`create_progress`）、指标（`MetricsCollector`）、Schema 辅助（`detect_autoincrement`）等内部工具。

## 本目录规则

- 保持可选依赖边界。`faker`、`mimesis`、`sqlseed_ai`、`mcp` 相关导入应维持懒加载或局部导入。
- 公共 API 的签名、默认值和导出项要与 CLI、配置模型和测试保持一致。
- `generate_choice(choices)` 是唯一一个保留位置参数的 Provider 方法；不要在 Protocol、Provider 或调用点上把它"统一修正"掉。
- CLI 应继续做薄封装。参数校验、生成逻辑和数据库交互应尽量留在库层，而不是 click 回调里。
- 涉及 SQL 的代码走 `quote_identifier()` 和参数化查询；适配器层尤其不要引入新的字符串拼接 SQL。
- 谨慎处理运行时依赖方向。`core` 负责编排；下层模块不要为了方便开始依赖编排器本身。
- 修改默认值、回退逻辑、配置 schema 或 entry point 时，同时检查 README 与相应测试。
- `_version.py` 使用 `importlib.metadata.version("sqlseed")` 动态获取版本，回退 `"0.0.0+unknown"`。

## 公共导出

`__init__.py` 导出：`ColumnConfig`、`TableConfig`、`GeneratorConfig`、`ProviderType`、`DataOrchestrator`、`GenerationResult`、`fill`、`connect`、`preview`、`fill_from_config`、`load_config`、`__version__`。

## 评审热点

- `generators/stream.py` 负责本地 RNG、null_ratio、外键/template pool 取值，以及 `choice` / `foreign_key` 的本地特判；其他未知生成器会继续抛 `UnknownGeneratorError`。
- `database/` 代码必须同时兼容 `sqlite-utils` 路径和原生 sqlite3 回退路径。`BaseSQLiteAdapter` 提供共享实现，子类只需实现 `_get_execute_fn()`、`get_column_info()`、`close()`。
- `plugins/hookspecs.py` 是外部插件契约；签名变化会破坏第三方插件。
- `config/models.py` 与 `config/loader.py` 决定 YAML/JSON 兼容性，改动时要关注回放和快照。
- `cli/main.py` 的 `ai-suggest` 命令依赖 `sqlseed_ai`，通过 `HAS_AI_PLUGIN` 标志守卫。

## 验证

- 公共 API 与 CLI：`pytest tests/test_public_api.py tests/test_cli.py`
- 核心子目录：`pytest tests/test_core tests/test_generators tests/test_database tests/test_plugins tests/test_config`
- 全仓检查：`mypy`, `ruff check src/ tests/`, `pytest`
