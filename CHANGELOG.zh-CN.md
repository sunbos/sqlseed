# 变更日志

[English](CHANGELOG.md) | **[中文](CHANGELOG.zh-CN.md)**

本项目所有重要变更将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，
本项目遵循[语义化版本](https://semver.org/spec/v2.0.0.html)。

## [v0.1.18]

### 新增

- 列映射器 `_to_snake_case()` 规范化：camelCase/PascalCase/Hungarian 列名（`sOrderNo`、`sItemNo`、`userName`、`isActive`）在直接匹配失败后自动通过 snake_case 回退解析
- 敏感标识符模式规则：`user_no`、`card_no`、`card_number`、`identity_no`（及 Hungarian 变体 `sUserNo`、`sCardNo`）映射为脱敏字符串，防止真实值通过 FK 解析或 SharedPool 泄露
- `tests/test_mapper_camelcase.py` — 23 个测试用例，覆盖 camelCase 映射、敏感字段脱敏和 `_to_snake_case()` 辅助函数

### 变更

- `pyproject.toml`：`sqlite-utils` 从必需依赖移至可选依赖（与 `HAS_SQLITE_UTILS` 回退逻辑一致）
- `pyproject.toml`：可选依赖组 `notebook` 重命名为 `tqdm`
- `pyproject.toml`：恢复 `plugins/` 到 sdist 排除列表；插件 `pyproject.toml` 新增 sdist 排除配置

### 修复

- `test_fill_with_snapshot` 通过 `monkeypatch.setenv` 将 `SQLSEED_CACHE_DIR` 设置为 `tmp_path`，修复默认缓存目录无写入权限时的 `PermissionError`

## [v0.1.17]

### 新增

- `RichProgressBackend` 新增 `ascii_only` 参数：启用时使用 `"line"` 旋转符（`|/-\`）并省略 `BarColumn`，避免 GBK/Big5/CP936 编码终端的 `UnicodeEncodeError`
- `_can_render_unicode()` 缓存辅助函数，检测 stdout 是否能编码 Rich 的盲文/方块字符（U+280B, U+2588, U+2591）
- `create_progress()` 在 `_can_render_unicode()` 返回 `False` 时自动回退到 `ascii_only=True`，并输出 debug 日志
- `DataOrchestrator` 新增 SQL 操作方法：`execute(sql, params)`、`query(sql, params)`、`fetch_one(sql, params)`、`fetch_all(sql, params)` 用于直接数据库交互
- `BaseSQLiteAdapter._execute(sql, params)` 参数化 SQL 执行方法
- `DatabaseAdapter` 协议新增 `_execute` 方法签名

### 变更

- `RichProgressBackend` 刷新频率设为 1 Hz（原默认 10 Hz），减少终端闪烁
- 测试套件：`TestRichProgressBackend` 和 `TestRichProgressBackendAsciiOnly` 通过 `pytest.mark.parametrize` 合并，消除代码重复

### 修复

- Windows 兼容性：GBK/GB2312/Big5/CP936 编码终端不再因 Rich 进度条的 Unicode 字符而崩溃
- `.gitignore`：移除 `*汇总.md` 规则（不再需要）

## [v0.1.16]

### 新增

- `_utils/paths.py` — `get_cache_dir(subdir)` 平台标准缓存目录工具（macOS `~/Library/Caches/sqlseed/`，Linux `~/.cache/sqlseed/`，Windows `%LOCALAPPDATA%/sqlseed/`），支持 `SQLSEED_CACHE_DIR` 环境变量覆盖
- `_utils/progress.py` 重构为 Strategy Pattern 多后端架构：`RichProgressBackend`（终端）、`TqdmNotebookBackend`（Jupyter）、`NullProgressBackend`（禁用），含自动环境检测
- `generators/_protocol.py` 新增 `GenerationError`（可重试运行时错误）和 `ConfigurationError`（不可重试配置错误）异常类
- `ColumnConfig` 新增 `normalize_dict_input` model_validator：支持 `type` 作为 `generator` 别名、未知键自动归入 `params`、嵌套 `params` 展平
- `DataStream` 新增 UNIQUE 约束耗尽警告日志，包含列名和生成器详情
- `DataStream` RuntimeError 消息现在包含非 skip 列名，便于快速定位问题
- Jupyter Notebook 教程系列（`examples/notebooks/`）：快速上手、列映射、生成器、数据库关联、表达式/DAG、AI 配置、MCP 服务器、测试模式、工具类、CLI 参考

### 变更

- `SnapshotManager` 默认目录从 `./snapshots` 改为平台缓存目录（`get_cache_dir("snapshots")`）
- `AiConfigRefiner` 默认缓存目录从 `.sqlseed_cache/ai_configs/` 改为平台缓存目录（`get_cache_dir("ai_configs")`）
- `cli/main.py` `inspect --show-mapping` 现在使用 `orch._resolve_specs()` 显示准确的列映射（此前使用 `orch.map_column(col)` 会跳过 FK 解析）
- `cli/main.py` `fill` 命令现在会将 `result.errors` 的警告输出到 stderr
- `orchestrator._resolve_user_configs` 支持 dict 风格的 `derive_from`/`expression` 列配置
- 示例数据库（`examples/build_demo_db.py`）重写为幂等 schema 初始化（`ensure_db()`），不再内置种子数据
- **⚠️ Breaking**: `register_shared_pool` 现在只注册 PK 和 FK 列到 SharedPool（此前会注册所有非 PK-skip 列）。同名非 PK/FK 列的隐式跨表关联需通过 `ColumnAssociation` 显式声明
- UNIQUE 列不再被 SharedPool 隐式关联或 template pool 覆盖，避免生成重复值导致 `IntegrityError`

### 修复

- `orchestrator.fill_table` 现在捕获 `sqlite3.IntegrityError`，避免 UNIQUE/FK 冲突导致未处理崩溃
- `UniqueAdjuster` 使用 `params.get("max_length", max_length)` 防止 `max_length` 缺失时的 `KeyError`
- `DataStream._attempt_node_generation` 优雅捕获生成器异常，不再向上传播
- 回溯/无值日志级别从 `warning` 降为 `debug`，减少日志噪音

## [v0.1.15]

### 修复
- CI: 移除 `ExpressionEngine.evaluate` 中不必要的 try/except，解决 SonarCloud S2737 和 CodeFlow try-except-raise 警告
- CI: 为 `PluginMediator.apply_template_pool` 中的 `list()` 调用添加注释说明其必要性（SonarCloud S7504）

## [v0.1.14]

### 修复
- CI: 修复 `test_doc_sync.py` 中的 ruff SIM114/SIM102 lint 错误
- CI: 移除 `test_doc_sync.py` 中所有正则表达式，解决 SonarCloud S5852 安全热点
- CI: 降低 `_extract_number_before_keyword` 辅助函数的认知复杂度

### 新增
- CLAUDE.md 中添加文档同步规则映射表
- 文档同步验证测试 (`tests/test_doc_sync.py`)

## [v0.1.13]

### 新增

#### 核心引擎
- 跨表关联支持：`ColumnAssociation` 配置模型，支持显式声明源表/源列映射
- 隐式关联：`SharedPool` 通过同名列自动匹配跨表 FK 引用
- `EnrichmentEngine` 数据分布推断，从现有表数据推断枚举列和值范围
- `UniqueAdjuster` 唯一列参数自动调整，确保生成数据满足 UNIQUE 约束
- `database/_compat.py` 新增 `HAS_SQLITE_UTILS` 标志，运行时检测 sqlite-utils 可用性

#### 数据生成器
- 新增 7 个生成器类型：`username`、`city`、`country`、`state`、`zip_code`、`job_title`、`country_code`
- `ColumnMapper` 精确匹配规则从 68 扩展到 74 条

#### AI 插件（sqlseed-ai）
- 自动模型选择：`_model_selector` 从 OpenRouter 免费模型列表中按优先级自动选择
- 结构化输出：`response_format: json_object` 强制 LLM 返回 JSON
- Few-shot 示例库：4 个典型场景（用户表、银行卡表、订单表、员工表）
- `AiConfigRefiner` 自纠正闭环：自动检测并修复无效配置，最多 3 轮重试
- 文件缓存：`.sqlseed_cache/ai_configs/` 带 schema hash 校验，`--no-cache` 跳过
- 预计算模板池：`sqlseed_pre_generate_templates` Hook，AI 为复杂列预生成候选值
- 错误摘要系统：`errors.py` 智能分类错误类型
- 环境变量：`SQLSEED_AI_API_KEY`、`SQLSEED_AI_BASE_URL`、`SQLSEED_AI_MODEL`、`SQLSEED_AI_TIMEOUT`

#### MCP 服务器（mcp-server-sqlseed）
- `sqlseed_execute_fill` 新增 `enrich` 参数，支持数据分布推断
- `sqlseed_inspect_schema` 返回 `schema_hash` 字段

#### CLI
- `fill` 命令新增 `--enrich` 标志
- `fill` 命令新增 `--no-ai` 标志，跳过 AI 建议和模板生成
- `ai-suggest` 命令新增 `--verify/--no-verify`、`--timeout` 参数
- `fill` 命令使用 `--config` 时 `db_path` 改为可选

#### 测试与示例
- 新增 `test_cli_yaml_priority.py`，覆盖 CLI YAML 优先级场景
- 新增 `examples/ai_generation_demo.py` 使用示例

### 变更

- `ExpressionEngine` 正则表达式模式简化
- 代码结构和类型注解优化，移除不必要的延迟导入
- CI 工作流扩展：ruff 检查覆盖 `plugins/` 目录，添加并发控制
- 更新依赖版本限制
- 全面重写项目文档：CLAUDE.md、README.md、GEMINI.md、AGENTS.md、architecture.md
- 重写 `plugins/sqlseed-ai/README.md` 和 `plugins/mcp-server-sqlseed/README.md`

### 修复

- ruff lint 清理，允许中文全角字符（`：`、`（`、`）`）
- 移除 `sqlite3.OperationalError` 不必要的捕获
- `ProviderRegistry.register_from_entry_points()` 修正非 provider 入口点的区分逻辑

### 移除

- 移除 `docs/superpowers/` 目录（过时的设计文档）
- 移除 `suggest.py` 和 `nl_config.py`，功能由 `SchemaAnalyzer` + `AiConfigRefiner` 替代

## [v0.1.12]

### 新增

#### 核心引擎
- 核心编排引擎 `DataOrchestrator`，支持流式批量生成
- `ColumnMapper` 9 级策略链（精确匹配 → 模式匹配 → 类型回退 → 默认）
- `DatabaseAdapter` Protocol，含 `SQLiteUtilsAdapter` 和 `RawSQLiteAdapter`
- `PragmaOptimizer` 三级优化（LIGHT / MODERATE / AGGRESSIVE）
- `DataProvider` Protocol，含 `BaseProvider`、`FakerProvider`、`MimesisProvider`
- `DataStream` 流式数据生成器，内存高效的批量处理
- `RelationResolver` 外键依赖拓扑排序
- 基于 `pluggy` 的插件系统，11 个 Hook 点
- CLI 命令：`fill`、`preview`、`inspect`、`init`、`replay`、`ai-suggest`
- Python API：`sqlseed.fill()`、`sqlseed.connect()`、`sqlseed.fill_from_config()`、`sqlseed.preview()`
- YAML/JSON 配置文件支持
- 配置快照保存与回放
- SQL 注入防护（`quote_identifier()` 工具）

#### v2.0 — 列 DAG 与表达式引擎
- `ColumnDAG` 列依赖解析，基于拓扑排序
- `ExpressionEngine` 基于 `simpleeval` 的安全表达式求值，带基于线程的超时保护
- `ConstraintSolver` 唯一性约束求解，支持重试和回溯
- `TransformLoader` 用户 Python 脚本动态加载（`importlib`）
- `SharedPool` 跨表值共享，维持引用完整性
- `IndexInfo` 数据类和 `get_index_info()` 加入 `DatabaseAdapter` Protocol
- `get_sample_rows()` 方法加入 `DatabaseAdapter` Protocol，用于上下文嗅探
- `sqlseed_ai_analyze_table` Hook（firstresult），AI 驱动的 Schema 分析
- `sqlseed_shared_pool_loaded` Hook，跨表关联追踪

#### AI 插件（sqlseed-ai）
- `SchemaAnalyzer` LLM 集成（OpenAI 兼容 API）
- 上下文嗅探：提取列、索引、样本数据、外键供 LLM 分析
- `AIConfig` 可配置模型、API Key 和 Base URL
- CLI `ai-suggest` 命令，AI 驱动的 YAML 生成

#### MCP 服务器（mcp-server-sqlseed）
- `sqlseed_inspect_schema` 工具 — 检查数据库 Schema
- `sqlseed_generate_yaml` 工具 — AI 驱动的 YAML 配置生成
- `sqlseed_execute_fill` 工具 — 执行数据生成
- 基于 FastMCP 的服务器

### 修复
- Hook `firstresult` 语义与设计文档对齐
- `validate_table_name` 增加正则验证
- 表达式引擎增加超时保护（默认 5 秒）
- `fill_from_config` 中 transform 属性正确传递
