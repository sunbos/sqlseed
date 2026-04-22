# sqlseed - 项目上下文

## 项目概述
`sqlseed` 是一个声明式 SQLite 测试数据生成工具包，使用 Python（>=3.10）编写。它旨在以最少的配置智能生成大量高质量测试数据。该工具可以自动推断数据库 Schema 并选择合适的数据生成策略，同时通过 Python API 或声明式 YAML/JSON 配置提供精细控制。

核心特性包括：
- 支持高性能数据生成引擎 Mimesis（推荐）和 Faker
- 通过 8 级策略链实现智能列映射（包含 enum 推断、唯一性自适应等）
- 自动外键解析和拓扑排序依赖管理
- SQLite PRAGMA 批量处理优化（通过 `PragmaOptimizer` 支持 LIGHT / MODERATE / AGGRESSIVE 策略，智能动态优化）
- 基于 `pluggy` 的健壮插件架构，11 个生命周期 Hook
- 官方 AI 驱动插件（`sqlseed-ai`），支持 LLM 数据生成
- MCP 服务器（`mcp-server-sqlseed`），通过 Model Context Protocol 与 AI 助手集成（默认区域为 `en_US`）
- 跨表 SharedPool 维持引用完整性
- 安全表达式引擎，支持超时保护的派生列计算和回溯约束求解
- 快照回放机制，支持精确复现数据生成

## 项目架构
- **`src/sqlseed/core/`**：核心编排引擎，处理主流程编排（`orchestrator.py`）、生成结果统计（`result.py`）、Schema 推断（`schema.py`）、策略映射（`mapper.py`）、关系解析（`relation.py`）、列依赖 DAG（`column_dag.py`）、表达式求值（`expression.py`）、约束求解（`constraints.py`）、Transform 加载（`transform.py`）、列数据增强（`enrichment.py`，如枚举推断）、唯一性策略调整（`unique_adjuster.py`）以及插件/AI建议中介层（`plugin_mediator.py`）。
- **`src/sqlseed/generators/`**：数据 Provider 注册表及 Mimesis、Faker 和流式生成适配器（`stream.py`）。包含协议定义（`_protocol.py`）、基础实现（`base_provider.py`）、注册机制（`registry.py`）。
- **`src/sqlseed/database/`**：SQLite 交互适配器（`sqlite_utils_adapter.py` 和 `raw_sqlite_adapter.py`），含 PRAGMA 优化（`optimizer.py`）。Protocol（`_protocol.py`）包含 `ColumnInfo`、`ForeignKeyInfo`、`IndexInfo` 等元数据定义，以及数据查询方法。
- **`src/sqlseed/plugins/`**：基于 `pluggy` 的插件管理和 Hook 规范定义（`hookspecs.py` 和 `manager.py`）。
- **`src/sqlseed/config/`**：使用 `pydantic` 模型、YAML/JSON 加载器（`loader.py`、`models.py`）以及支持 CLI `replay` 命令的运行快照（`snapshot.py`）的配置管理。
- **`src/sqlseed/cli/`**：基于 `click` 的命令行接口（`main.py` 提供 fill, preview, inspect, init, replay, ai-suggest）。
- **`src/sqlseed/_utils/`**：内部工具包，包含 SQL 安全处理（`sql_safe.py`）、共享 Schema 辅助函数（`schema_helpers.py`）、性能度量收集（`metrics.py`）、进度条封装（`progress.py`，基于 `rich`）和日志封装（`logger.py`，基于 `structlog`）。
- **`plugins/sqlseed-ai/`**：独立包，提供 OpenAI 兼容的 LLM 驱动生成能力，含 `analyzer.py`（LLM 表级分析）、`refiner.py`（自纠正闭环）、`errors.py`（错误摘要）、`examples.py`（Few-shot 示例）、`provider.py`（AI Provider 兼容性空壳）、`config.py`（AIConfig 配置模型）、`_client.py`（API 客户端）和 `_json_utils.py`（JSON 解析）。
- **`plugins/mcp-server-sqlseed/`**：MCP 服务器，基于 FastMCP 提供一个 Resource（`sqlseed://schema/{db_path}/{table_name}`）和三个核心 Tool（`sqlseed_inspect_schema`、`sqlseed_generate_yaml`、`sqlseed_execute_fill`），用于实现与 AI 助手的无缝集成（由 `server.py` 和 `config.py` 驱动）。
- **`docs/`**：项目文档，包括架构（`architecture.md`）、评估（`evaluation.md`），以及特定工具集成的设计与规划文档（位于 `superpowers/plans/` 和 `superpowers/specs/` 中）。

## 构建与运行
项目使用 `hatch` 作为构建后端和包管理器。

**安装：**
```bash
# 安装核心及所有可选依赖（Mimesis、Faker）
pip install -e ".[dev,all]"

# 安装 AI 插件（可选）
pip install -e "./plugins/sqlseed-ai"

# 安装 MCP 服务器（可选）
pip install -e "./plugins/mcp-server-sqlseed"
```

**CLI 使用示例：**
```bash
# 零配置生成
sqlseed fill test.db --table users --count 10000

# YAML 配置驱动生成
sqlseed fill --config generate.yaml

# 数据预览（不写入数据库）
sqlseed preview test.db --table users --count 5

# 查看数据库表及特定表的列映射策略
sqlseed inspect test.db --table users --show-mapping

# 生成配置模板
sqlseed init generate.yaml --db test.db

# 保存并回放快照
sqlseed fill test.db --table users --count 10000 --snapshot
sqlseed replay snapshots/2026-04-12_users.yaml

# AI 驱动的 YAML 建议
sqlseed ai-suggest test.db --table users --output users.yaml
```

**Python API 使用示例：**
```python
import sqlseed

# 简单填充
result = sqlseed.fill("test.db", table="users", count=1000)
print(f"耗时: {result.elapsed:.2f}s, 插入: {result.count} 行")

# 使用 Orchestrator (上下文管理器)
with sqlseed.connect("test.db", provider="mimesis") as db:
    db.fill("users", count=5000)
```

## 开发规范
- **测试（`pytest`）**：项目维护了高达 94% 的测试覆盖率。`tests/` 下包含针对各个模块的子目录测试（`test_config`、`test_core`、`test_database`、`test_generators`、`test_plugins`、`test_utils`）以及性能基准测试（`benchmarks/`）。重点覆盖了约束回溯 (`ConstraintSolver`)、多线程安全的派生列求值引擎以及数据去重的递归降级逻辑。
  - 运行测试：`pytest`
  - 运行带详细堆栈测试：`pytest --tb=long -v`
  - AI 插件测试使用 `pytest.importorskip("sqlseed_ai")` 处理可选依赖。
- **代码检查与格式化（`ruff`）**：执行严格的代码检查规则（配置见 `pyproject.toml` 中的 `[tool.ruff]`）。
  - 运行检查：`ruff check src/ tests/ plugins/`
- **类型检查（`mypy`）**：严格静态类型是核心要求。
  - 运行类型检查：`mypy src/sqlseed/ plugins/`
- **设计哲学**：代码库推崇 Protocol 驱动设计（`typing.Protocol`）、显式配置（`pydantic`）和通过 Hook 系统实现高扩展性。不安全操作封装在 `_utils` 模块中（如 `sql_safe.py`）。
- **表达式安全**：`ExpressionEngine` 使用 `simpleeval` 并配合隔离副本及多线程超时保护，实现并发安全，防止用户提供的派生列配置出现无限循环或变量污染。
