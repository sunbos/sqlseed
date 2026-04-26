# AGENTS.md — sqlseed

## 项目目的

- `sqlseed` 是一个声明式 SQLite 测试数据生成工具包，主入口包括 Python API、Click CLI、pluggy 插件体系，以及两个可选子包：`sqlseed-ai` 和 `mcp-server-sqlseed`。
- 优先在现有架构内演进。除非任务明确要求，不要重排公开 API、插件协议、包边界或配置格式。

## 顶层结构

- `src/sqlseed/`：主包。公共 API、CLI、编排、生成器、数据库适配器、配置与 hook 规范都在这里。
- `plugins/sqlseed-ai/`：可选 AI 插件包，通过 `sqlseed` entry point 接入（`ai = "sqlseed_ai:plugin"`）。包含动态模型选择（`_model_selector.py`）和超时回退机制。
- `plugins/mcp-server-sqlseed/`：可选 MCP 服务器包，封装 FastMCP 工具与资源（`mcp-server-sqlseed = "mcp_server_sqlseed:main"`）。
- `tests/`：单元、集成、插件与基准测试（约 300+ 测试函数）。
- `docs/`：文档与计划，不是运行时代码。

## 子级 AGENTS

- `src/sqlseed/AGENTS.md`
- `src/sqlseed/config/AGENTS.md`
- `src/sqlseed/core/AGENTS.md`
- `src/sqlseed/database/AGENTS.md`
- `src/sqlseed/generators/AGENTS.md`
- `src/sqlseed/plugins/AGENTS.md`
- `plugins/sqlseed-ai/AGENTS.md`
- `plugins/mcp-server-sqlseed/AGENTS.md`
- `tests/AGENTS.md`

进入这些目录工作时，优先读取最近的子级 `AGENTS.md`，只把根级规则当作全局补充。

## 常见落点

- 改公共 API：`src/sqlseed/__init__.py`
- 改 CLI：`src/sqlseed/cli/main.py`
- 改核心编排、推断、约束、SharedPool：`src/sqlseed/core/`
- 改 Provider、Registry、流式生成：`src/sqlseed/generators/`
- 改 SQLite 适配器与 PRAGMA 优化：`src/sqlseed/database/`
- 改配置模型、加载与快照：`src/sqlseed/config/`
- 改 hook 规范或插件管理：`src/sqlseed/plugins/`
- 改 AI 建议与自纠正：`plugins/sqlseed-ai/`
- 改动态模型选择与回退：`plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py`
- 改 MCP 工具或资源：`plugins/mcp-server-sqlseed/`
- 补测试：`tests/`

## 全局规则

- 目标版本是 Python 3.10+。保留 `from __future__ import annotations`，并为新增或修改的函数写完整类型注解。
- 公共函数默认使用仅关键字参数；已知例外是 `generate_choice(choices)`，不要把它误改成仅关键字接口。
- 结构化日志统一走 `sqlseed._utils.logger.get_logger(__name__)`。
- 处理 SQL 标识符时始终使用 `sqlseed._utils.sql_safe.quote_identifier()`；不要对表名、列名或用户值拼 f-string SQL。
- 保持可选依赖可选：核心包不能因为 `faker`、`mimesis`、`openai` 或 `mcp` 缺失而无法导入。
- 需要随机性时优先复用 Provider 自带 RNG 或局部 RNG，不要引入新的模块级全局随机状态。
- `pluggy` 的项目名固定为 `sqlseed`；外部插件通过 `[project.entry-points."sqlseed"]` 发现。
- 公开行为变化必须配套测试更新。这个仓库默认跑覆盖率，回归很容易在 `pytest` 中暴露。
- 如果你因为架构变化更新了根级 agent 文档，也检查 `CLAUDE.md` 和 `GEMINI.md` 是否已经过时。

## 公共 API 表面

`src/sqlseed/__init__.py` 导出以下公共接口：

| API | 签名 | 用途 |
|-----|------|------|
| `sqlseed.fill` | `(db_path, *, table, count=1000, columns=None, provider="mimesis", locale="en_US", seed=None, batch_size=5000, clear_before=False, optimize_pragma=True, enrich=False, transform=None) -> GenerationResult` | 单表零配置填充 |
| `sqlseed.connect` | `(db_path, *, provider="mimesis", locale="en_US", optimize_pragma=True) -> DataOrchestrator` | 返回 `DataOrchestrator` 上下文管理器 |
| `sqlseed.preview` | `(db_path, *, table, count=5, columns=None, provider="mimesis", locale="en_US", seed=None, enrich=False, transform=None) -> list[dict]` | 预览生成数据，不写入 |
| `sqlseed.fill_from_config` | `(config_path) -> list[GenerationResult]` | 从 YAML/JSON 配置批量填充 |
| `sqlseed.load_config` | `(path) -> GeneratorConfig` | 加载配置文件为 `GeneratorConfig` |

导出的类型：`ColumnConfig`、`TableConfig`、`GeneratorConfig`、`ProviderType`、`DataOrchestrator`、`GenerationResult`。

## 配置模型层次结构

```
GeneratorConfig (全局)
├── db_path: str
├── provider: ProviderType  (base|faker|mimesis|custom|ai)
├── locale: str = "en_US"
├── tables: list[TableConfig]
├── associations: list[ColumnAssociation]  (跨表隐式关联)
├── optimize_pragma: bool = True
├── log_level: str = "INFO"
└── snapshot_dir: str | None

TableConfig (单表)
├── name: str
├── count: int = 1000
├── batch_size: int = 5000
├── columns: list[ColumnConfig]
├── clear_before: bool = False
├── seed: int | None
├── transform: str | None  (Python 脚本路径)
└── enrich: bool = False

ColumnConfig (列级，支持两种互斥模式)
├── 源列模式: generator + params + null_ratio + provider
├── 派生列模式: derive_from + expression
└── constraints: ColumnConstraintsConfig | None
    ├── unique: bool
    ├── min_value / max_value
    ├── regex: str | None
    └── max_retries: int = 100

ColumnAssociation (跨表关联)
├── column_name: str
├── source_table: str
├── source_column: str | None = None  (源表列名，默认等于 column_name)
├── target_tables: list[str]
└── strategy: str = "shared_pool"
```

**模式互斥验证**：`derive_from` 和 `generator` 不可同时使用（Pydantic `model_validator`）。`derive_from` 必须配对 `expression`。

## 核心编排流程

`DataOrchestrator.fill_table()` 是主入口，执行链路：

```
1.  _ensure_connected()         → 连接数据库、加载插件、注册 Provider、创建 PluginMediator
2.  optimize_for_bulk_write()   → 三级 PRAGMA 优化（如果 optimize_pragma=True）
3.  clear_table()               → 如果 clear_before=True，清空表
4.  _resolve_specs()            → 合并 Schema 推断 + 用户配置 + 映射 + 唯一性 + FK 解析
    4a. get_column_info()       → 推断 Schema
    4b. _resolve_user_configs() → 合并用户 ColumnConfig 配置
    4c. map_columns()           → 9 级策略链映射
    4d. detect_unique_columns() → 检测唯一列
    4e. EnrichmentEngine.apply() → [enrich=True] 数据分布推断
    4f. UniqueAdjuster.adjust() → 唯一列参数调整
    4g. resolve_foreign_keys()  → FK 解析 + SharedPool 隐式关联
    4h. apply_associations()    → [有 associations 配置时] 显式跨表关联（使用 source_column 查源表列）
5.  apply_ai_suggestions()      → AI Hook 分析（通过 PluginMediator）
6.  apply_template_pool()       → AI 预计算模板池（通过 PluginMediator）
7.  _build_stream()             → 创建 ColumnDAG、ExpressionEngine、ConstraintSolver、加载 Transform
8.  sqlseed_before_generate Hook
9.  DataStream.generate()       → 逐批 yield 数据
10. 每批：before_insert → apply_batch_transforms → batch_insert → after_insert
11. sqlseed_after_generate Hook
12. register_shared_pool()      → 注册值到 SharedPool（非 skip 列 + 自增主键列）
13. sqlseed_shared_pool_loaded Hook
14. restore_settings()          → [finally] 恢复 PRAGMA 设置
```

**注意**：`preview_table()` 不调用 AI 建议和模板池（步骤 5-6），不调用 before_generate/after_generate Hook，但**会**调用 `apply_batch_transforms()`。

## DataProvider Protocol 与生成器体系

`DataProvider` Protocol 定义了统一的生成接口：

```python
@runtime_checkable
class DataProvider(Protocol):
    @property
    def name(self) -> str: ...
    def set_locale(self, locale: str) -> None: ...
    def set_seed(self, seed: int) -> None: ...
    def generate(self, type_name: str, **params: Any) -> Any: ...
```

`generate()` 方法通过 `GeneratorDispatchMixin._GENERATOR_MAP` 分派到 24 个内部方法：

`string`、`integer`、`float`、`boolean`、`bytes`、`name`、`first_name`、`last_name`、
`email`、`phone`、`address`、`company`、`url`、`ipv4`、`uuid`、`date`、
`datetime`、`timestamp`、`text`、`sentence`、`password`、`choice`、`json`、`pattern`

未知 `type_name` 会抛出 `UnknownGeneratorError`（定义在 `generators/_protocol.py`）。

继承链：`GeneratorDispatchMixin` → `BaseProvider` → `FakerProvider` / `MimesisProvider` / `AIProvider`

## DatabaseAdapter Protocol 方法完整列表

`connect`、`close`、`get_table_names`、`get_column_info`、`get_primary_keys`、
`get_foreign_keys`、`get_row_count`、`get_column_values`、`get_index_info`、
`get_sample_rows`、`batch_insert`、`clear_table`、`optimize_for_bulk_write`、
`restore_settings`、`__enter__`、`__exit__`

数据类：`ColumnInfo`、`ForeignKeyInfo`、`IndexInfo`（均为 `frozen` dataclass）。

适配器继承链：`BaseSQLiteAdapter`（共享基类）→ `SQLiteUtilsAdapter` / `RawSQLiteAdapter`

## 插件 Hook 完整列表（11 个）

| Hook | firstresult | 调用位置 |
|------|-------------|----------|
| `sqlseed_register_providers(registry)` | ✗ | `_ensure_connected()` |
| `sqlseed_register_column_mappers(mapper)` | ✗ | `_ensure_connected()` |
| `sqlseed_ai_analyze_table(...)` | ✓ | `apply_ai_suggestions()` |
| `sqlseed_before_generate(table_name, count, config)` | ✗ | `fill_table()` 主循环前 |
| `sqlseed_after_generate(table_name, count, elapsed)` | ✗ | `fill_table()` 完成后 |
| `sqlseed_transform_row(table_name, row)` | ✗ | （定义在 hookspecs，热路径） |
| `sqlseed_transform_batch(table_name, batch)` | ✗ | `apply_batch_transforms()` |
| `sqlseed_before_insert(table_name, batch_number, batch_size)` | ✗ | 每批写入前 |
| `sqlseed_after_insert(table_name, batch_number, rows_inserted)` | ✗ | 每批写入后 |
| `sqlseed_shared_pool_loaded(table_name, shared_pool)` | ✗ | `register_shared_pool()` 后 |
| `sqlseed_pre_generate_templates(...)` | ✓ | `apply_template_pool()` |

## ColumnMapper 9 级策略链

| 优先级 | 级别 | 规则数量 | 说明 |
|--------|------|----------|------|
| 1 | 自增主键 | — | PK + 自增/INTEGER → `skip` |
| 2 | 用户配置 | — | `ColumnConfig.generator` + params |
| 3 | 自定义精确匹配 | 动态 | `register_exact_rule()` 注册 |
| 4 | 内置精确匹配 | 68 规则 | `EXACT_MATCH_RULES` + `EXACT_MATCH_PARAMS`（28 预设） |
| 5 | DEFAULT 检查 | — | `default is not None` → `skip`/`__enrich__` |
| 6 | 自定义模式匹配 | 动态 | `register_pattern_rule()` 注册 |
| 7 | 内置模式匹配 | 25 正则 | `PATTERN_MATCH_RULES` |
| 8 | NULLABLE 回退 | — | `nullable` → `skip`/`__enrich__` |
| 9 | 类型忠实回退 | 22 类型 | `TYPE_FALLBACK_RULES`，解析 `VARCHAR(32)` 等括号参数 |

## 构建与验证

- 安装主包开发环境：`pip install -e ".[dev,all]"`
- 安装 AI 插件：`pip install -e "./plugins/sqlseed-ai"`
- 安装 MCP 插件：`pip install -e "./plugins/mcp-server-sqlseed"`
- Lint：`ruff check src/ tests/`
- 格式检查：`ruff format --check src/ tests/`
- 类型检查：`mypy`
- 全量测试：`pytest`

## 评审重点

- 公开 API、CLI 参数、配置模型和 hook 签名都属于外部契约，改动前先查对应测试与 README。
- 核心编排代码有不少"软失败"路径：Provider 回退、AI 建议缺席、批量 transform 链式透传、异常转 `GenerationResult.errors`。如果要改成硬失败，必须同步更新测试与文档。
- 插件包是独立分发单元。不要把插件实现细节反向塞回主包导入路径里。
- AI 插件默认模型为 `None`（自动选择），通过 `_model_selector.select_best_free_model()` 动态获取 OpenRouter 最受欢迎的免费模型。`call_llm()` 实现超时回退：`APITimeoutError`/`APIConnectionError` 时自动回退到优先级列表中的下一个模型（最多 3 个）。`PREFERRED_FREE_MODELS` 优先级列表需定期手动更新。
