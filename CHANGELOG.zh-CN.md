# 变更日志

[English](CHANGELOG.md) | **[中文](CHANGELOG.zh-CN.md)**

本项目所有重要变更将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，
本项目遵循[语义化版本](https://semver.org/spec/v2.0.0.html)。

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
