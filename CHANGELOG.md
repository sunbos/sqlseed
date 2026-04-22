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
- 自然语言配置（`nl_config.py`，已移除，功能由 `SchemaAnalyzer` + `AiConfigRefiner` 替代）

#### AI Evolution — 智能增强
- 结构化输出迁移：YAML → JSON，`response_format` 强制 JSON 输出
- 自纠正闭环：`AiConfigRefiner` 自动检测并修复无效配置，支持最多 3 轮重试
- 错误摘要系统：`errors.py` 智能分类错误（未知生成器、Pydantic 验证、表达式超时等）
- 数据分布增强：`profile_column_distribution()` 分析列数据分布，注入 LLM 上下文
- Few-shot 示例库：4 个典型场景示例（用户表、银行卡表、订单表、员工表）
- 文件缓存：带 schema hash 校验的配置缓存，`--no-cache` 标志跳过缓存
- 预计算模板池：`sqlseed_pre_generate_templates` Hook，AI 为复杂列预生成值
- MCP 增强：Schema Resource、schema_hash 工具返回值

#### 架构优化
- 约束求解器回溯机制：`RegisterResult` + `try_register()`，派生列 UNIQUE 约束失败时回溯源列
- Refiner 解耦：`get_column_names()` + `get_skippable_columns()` 公开接口，不再访问私有属性
- 语义化异常：`UnknownGeneratorError` 替代脆弱的字符串匹配
- AI 建议扩展：支持 `integer`、`date`、`datetime`、`choice` 类型列
- 词边界列匹配：`_is_simple_column()` 使用正则词边界替代子串匹配
- 复合唯一约束：`check_composite()` + `unregister_composite()`
- 大数据集优化：`probabilistic=True` 启用 hash-based 去重，降低内存占用

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
- `ProviderRegistry.register_from_entry_points()` 修正 provider 类与普通插件入口点的区分逻辑，非 provider 入口点（如 `sqlseed_ai:plugin`）不再产生误报 warning

### 变更
- 移除 `suggest.py`（`ColumnSuggester`）和 `nl_config.py`（`NLConfigGenerator`），其功能由 `SchemaAnalyzer` + `AiConfigRefiner` 完全替代。如有外部代码直接 `from sqlseed_ai.suggest import ColumnSuggester` 或 `from sqlseed_ai.nl_config import NLConfigGenerator`，将产生 `ImportError`
- `plugins/sqlseed-ai/README.md` 功能描述与当前实际入口对齐，移除未对外提供的 "Column-level Suggestions" / "Natural Language Config" 描述
