# 变更日志

本项目所有重要变更将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，
本项目遵循[语义化版本](https://semver.org/spec/v2.0.0.html)。

## [未发布]

### 新增

#### 核心引擎
- 核心编排引擎 `DataOrchestrator`，支持流式批量生成
- `ColumnMapper` 8 级策略链（精确匹配 → 模式匹配 → 类型回退 → 默认）
- `DatabaseAdapter` Protocol，含 `SQLiteUtilsAdapter` 和 `RawSQLiteAdapter`
- `PragmaOptimizer` 三级优化（LIGHT / MODERATE / AGGRESSIVE）
- `DataProvider` Protocol，含 `BaseProvider`、`FakerProvider`、`MimesisProvider`
- `DataStream` 流式数据生成器，内存高效的批量处理
- `RelationResolver` 外键依赖拓扑排序
- 基于 `pluggy` 的插件系统，10 个 Hook 点
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
- 默认模型：`qwen3-coder-plus`，支持环境变量覆盖
- CLI `ai-suggest` 命令，AI 驱动的 YAML 生成
- 自然语言配置（`nl_config.py`）

#### MCP 服务器（mcp-server-sqlseed）
- `sqlseed_inspect_schema` 工具 — 检查数据库 Schema（列、外键、索引、样本数据）
- `sqlseed_generate_yaml` 工具 — AI 驱动的 YAML 配置生成
- `sqlseed_execute_fill` 工具 — 执行数据生成（支持 YAML 配置）
- 基于 FastMCP 的服务器，支持 `python -m mcp_server_sqlseed`

### 修复
- Hook `firstresult` 语义与设计文档对齐（`transform_row` 和 `transform_batch`）
- `validate_table_name` 增加正则验证和适当警告
- 移除编排器中冗余的种子双重设置
- 将重复的 `_is_autoincrement` 逻辑提取到共享的 `schema_helpers` 工具
- 添加 `fill()` 别名到 `DataOrchestrator`，与设计文档 API 兼容
- CLI `fill` 命令使用 `--config` 时 `db_path` 改为可选
- 表达式引擎增加超时保护（默认 5 秒），防止无限循环
- 解决 `random.seed()` 类型异常（`rstr` 集成于流式生成器）
- `fill_from_config` 中 transform 属性正确传递到内部编排器
