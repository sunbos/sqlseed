# AGENTS.md — src/sqlseed

## 作用域

- 本目录拥有可导入的 `sqlseed` 主包。
- 修改这里的代码时，默认目标是保持 `import sqlseed` 轻量且稳定，即使可选依赖未安装也不应整体失效。

## 目录导航

- `core/`：主编排链路、列映射、表达式、约束、Transform、Enrichment、Relation、Schema。进入该目录前再读 `core/AGENTS.md`。
- `generators/`：`DataProvider` Protocol、Provider Registry、Base/Faker/Mimesis Provider、`DataStream`。
- `database/`：`DatabaseAdapter` Protocol、`sqlite-utils`/原生 sqlite3 适配器、PRAGMA 优化。
- `config/`：Pydantic 配置模型、YAML/JSON 加载、快照回放。
- `cli/`：Click 命令层，负责参数解析与输出展示。
- `plugins/`：hook 规范与 `PluginManager`，不是插件实现目录。
- `_utils/`：SQL 安全、日志、进度、指标等内部工具。

## 本目录规则

- 保持可选依赖边界。`faker`、`mimesis`、`sqlseed_ai`、`mcp` 相关导入应维持懒加载或局部导入。
- 公共 API 的签名、默认值和导出项要与 CLI、配置模型和测试保持一致。
- `generate_choice(choices)` 是唯一一个保留位置参数的 Provider 方法；不要在 Protocol、Provider 或调用点上把它“统一修正”掉。
- CLI 应继续做薄封装。参数校验、生成逻辑和数据库交互应尽量留在库层，而不是 click 回调里。
- 涉及 SQL 的代码走 `quote_identifier()` 和参数化查询；适配器层尤其不要引入新的字符串拼接 SQL。
- 谨慎处理运行时依赖方向。`core` 负责编排；下层模块不要为了方便开始依赖编排器本身。
- 修改默认值、回退逻辑、配置 schema 或 entry point 时，同时检查 README 与相应测试。

## 评审热点

- `generators/stream.py` 负责本地 RNG、null_ratio、外键/template pool 取值，以及未知生成器回退到字符串生成器的行为。
- `database/` 代码必须同时兼容 `sqlite-utils` 路径和原生 sqlite3 回退路径。
- `plugins/hookspecs.py` 是外部插件契约；签名变化会破坏第三方插件。
- `config/models.py` 与 `config/loader.py` 决定 YAML/JSON 兼容性，改动时要关注回放和快照。

## 验证

- 公共 API 与 CLI：`pytest tests/test_public_api.py tests/test_cli.py`
- 核心子目录：`pytest tests/test_core tests/test_generators tests/test_database tests/test_plugins tests/test_config`
- 全仓检查：`mypy`, `ruff check src/ tests/`, `pytest`
