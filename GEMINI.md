# sqlseed - 项目上下文

## 项目概述
`sqlseed` 是一个声明式 SQLite 测试数据生成工具包，使用 Python（>=3.10）编写。它旨在以最少的配置智能生成大量高质量测试数据。该工具可以自动推断数据库 Schema 并选择合适的数据生成策略，同时通过 Python API 或声明式 YAML/JSON 配置提供精细控制。

核心特性包括：
- 支持高性能数据生成引擎 Mimesis（推荐）和 Faker
- 通过 8 级策略链实现智能列映射
- 自动外键解析和拓扑排序依赖管理
- SQLite PRAGMA 批量处理优化
- 基于 `pluggy` 的健壮插件架构，10 个生命周期 Hook
- 官方 AI 驱动插件（`sqlseed-ai`），支持 LLM 数据生成
- MCP 服务器（`mcp-server-sqlseed`），通过 Model Context Protocol 与 AI 助手集成
- 跨表 SharedPool 维持引用完整性
- 安全表达式引擎，支持超时保护的派生列计算

## 项目架构
- **`src/sqlseed/core/`**：核心编排引擎，处理主流程编排（`orchestrator.py`）、生成结果统计（`result.py`）、Schema 推断（`schema.py`）、策略映射（`mapper.py`）、关系解析（`relation.py`）、列依赖 DAG（`column_dag.py`）、表达式求值（`expression.py`）、约束求解（`constraints.py`）和 Transform 加载（`transform.py`）。
- **`src/sqlseed/generators/`**：数据 Provider 注册表及 Mimesis、Faker 和流式生成适配器。
- **`src/sqlseed/database/`**：SQLite 交互适配器（`sqlite-utils` 和原生 `sqlite3`），含 PRAGMA 优化。Protocol 包含 `IndexInfo` 和 `get_sample_rows()`。
- **`src/sqlseed/plugins/`**：基于 `pluggy` 的插件管理和 Hook 规范定义（10 个 Hook）。
- **`src/sqlseed/config/`**：使用 `pydantic` 模型、YAML/JSON 加载器以及支持 CLI `replay` 命令的运行快照（`snapshot.py`）的配置管理。
- **`src/sqlseed/cli/`**：基于 `click` 的命令行接口（fill、preview、inspect、init、replay、ai-suggest）。
- **`plugins/sqlseed-ai/`**：独立包，提供 OpenAI 兼容的 LLM 驱动生成能力，含 `SchemaAnalyzer`。
- **`plugins/mcp-server-sqlseed/`**：MCP 服务器，提供三个工具（`sqlseed_inspect_schema`、`sqlseed_generate_yaml`、`sqlseed_execute_fill`）用于 AI 助手集成。

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

# AI 驱动的 YAML 建议
sqlseed ai-suggest test.db --table users --output users.yaml
```

**Python API 使用示例：**
```python
import sqlseed

# 简单填充
result = sqlseed.fill("test.db", table="users", count=1000)
print(f"耗时: {result.duration_ms}ms, 插入: {result.rows_inserted}")

# 使用 Orchestrator (上下文管理器)
with sqlseed.connect("test.db", provider="mimesis") as orch:
    orch.fill_table("users", count=5000)
```

## 开发规范
- **测试（`pytest`）**：项目维护全面的测试覆盖（单元、集成、CLI 和表达式引擎测试）。
  - 运行测试：`pytest`
  - AI 插件测试使用 `@pytest.mark.skipif` 处理可选依赖。
- **代码检查与格式化（`ruff`）**：执行严格的代码检查规则。
  - 运行检查：`ruff check src/ tests/`
- **类型检查（`mypy`）**：严格静态类型是核心要求。
  - 运行类型检查：`mypy src/sqlseed/`
- **设计哲学**：代码库推崇 Protocol 驱动设计（`typing.Protocol`）、显式配置（`pydantic`）和通过 Hook 系统实现高扩展性。不安全操作封装在 `_utils` 模块中（如 `sql_safe.py`）。
- **表达式安全**：`ExpressionEngine` 使用 `simpleeval` 并配合基于线程的超时保护，防止用户提供的表达式中出现无限循环。