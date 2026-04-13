# AGENTS.md — sqlseed AI Agent 指令

本文件为 AI 编码 Agent 在 sqlseed 代码库中工作提供上下文和指令。

## 项目概述

**sqlseed** 是一个声明式 SQLite 测试数据生成工具包。它编排成熟的库（`sqlite-utils`、`Faker`、`Mimesis`、`Pydantic`、`pluggy`）来提供零配置、声明式、基于 CLI 的 SQLite 数据库数据生成能力。

## 架构

```
src/sqlseed/
├── core/           → 编排层
│   ├── orchestrator.py     → 核心引擎（SharedPool + AI hook 集成）
│   ├── mapper.py           → 列名 → 生成器策略（8 级链）
│   ├── column_dag.py       → [v2.0] 列依赖 DAG + 拓扑排序
│   ├── expression.py       → [v2.0] 安全表达式引擎（simpleeval + 超时保护）
│   ├── constraints.py      → [v2.0] 唯一性/范围约束求解器（带回溯）
│   ├── transform.py        → [v2.0] 用户 Python 脚本动态加载器
│   ├── schema.py           → 从数据库推断 Schema（列信息、索引、样本数据）
│   ├── relation.py         → 外键解析 + 拓扑排序 + SharedPool
│   └── result.py           → GenerationResult 数据类
├── generators/     → 数据生成（Protocol、注册表、base/faker/mimesis Provider、流式）
├── database/       → 数据库访问（Protocol、sqlite-utils + 原生适配器、PRAGMA 优化器）
│                   → Protocol 包含 IndexInfo + get_sample_rows
├── plugins/        → 插件系统（pluggy hookspecs + 管理器，10 个 Hook）
├── config/         → 配置（Pydantic 模型，含 ColumnConstraints/derive_from/transform）
├── cli/            → CLI 接口（click 命令：fill、preview、inspect、init、replay、ai-suggest）
└── _utils/         → 内部工具（sql_safe、schema_helpers、metrics、progress、logger）

plugins/
├── sqlseed-ai/     → AI 插件（SchemaAnalyzer、LLM 集成、suggest/nl_config）
└── mcp-server-sqlseed/ → MCP 服务器（FastMCP：inspect_schema、generate_yaml、execute_fill）
```

## 关键设计决策

1. **基于 Protocol 的接口**：`DatabaseAdapter` 和 `DataProvider` 是 Python Protocol（结构化类型）。适配器必须满足这些接口，但不需要继承它们。

2. **插件系统**：基于 `pluggy`。Hook 定义在 `plugins/hookspecs.py` 中。插件通过 `pyproject.toml` 中的 `"sqlseed"` 组 entry-points 发现。

3. **流式架构**：`DataStream` 通过 `Iterator[list[dict]]` 批量生成数据，防止大数据集 OOM。

4. **多级列映射**：`ColumnMapper` 使用 8 级策略链：
   - 用户配置 > 自定义精确匹配 > 内置精确匹配 > 自定义模式匹配 > 内置模式匹配 > 跳过（DEFAULT/NULL） > 类型忠实回退 > 默认
   - **类型忠实回退**：`VARCHAR(32)` → 最长 32 字符的字符串；`INT8` → 0~255；`BLOB(1024)` → 1024 字节

5. **列依赖 DAG**（v2.0）：列可以通过 `derive_from` + `expression` 声明依赖关系。生成顺序由拓扑排序决定。派生列（如 `last_eight = card_number[-8:]`）在其源列之后计算。

6. **表达式引擎**（v2.0）：基于 `simpleeval` 的安全表达式求值器，具有基于线程的超时保护。支持字符串切片（`value[-8:]`）、函数调用（`upper(value)`）和数学运算。不允许 `import`/`exec`/文件 I/O。

7. **约束求解器**（v2.0）：通过重试和回溯处理唯一性约束。当派生列的唯一约束失败时，求解器回溯重新生成源列。

8. **Transform 脚本**（v2.0）：用户可以编写包含 `transform_row(row, ctx)` 函数的 Python 脚本。通过 `importlib` 动态加载。这是处理极端业务逻辑的逃生通道。

9. **PRAGMA 优化**：根据行数分三个等级 — LIGHT（<10K）、MODERATE（10K-100K）、AGGRESSIVE（>100K）。

10. **AI 作为一等公民插件**：`sqlseed-ai` 包是独立的可 pip 安装插件，通过 Hook 集成。AI 的角色是**顾问**（分析 Schema → 输出 YAML 建议 → 人工审核）。

11. **MCP 服务器**（v2.0）：`mcp-server-sqlseed` 提供三个 MCP 工具（`sqlseed_inspect_schema`、`sqlseed_generate_yaml`、`sqlseed_execute_fill`），使 AI 助手能够通过 Model Context Protocol 与 sqlseed 交互。

12. **跨表 SharedPool**（v2.0）：`relation.py` 中的 `SharedPool` 维护跨表值池以保持引用完整性。表填充完成后，其生成的值被注册到池中，供后续 FK 解析使用。

## 代码规范

- **Python 3.10+** — 使用 `X | Y` 联合语法，不使用 `Union[X, Y]`
- **`from __future__ import annotations`** — 每个模块必须包含
- **类型注解** — 所有函数必须有完整的类型注解
- **`ClassVar`** — 用于 dataclass/类的类级常量
- **结构化日志** — 使用 `structlog`，通过 `sqlseed._utils.logger.get_logger(__name__)`
- **SQL 安全** — 始终使用 `_utils/sql_safe.py` 中的 `quote_identifier()` 处理表/列名
- **禁止 f-string SQL** — 永远不要在 SQL 查询中使用包含用户提供的值的 f-string
- **测试** — 每个模块在 `tests/` 中有对应测试。目标覆盖率 ≥85%。

## 构建与测试

```bash
# 开发模式安装
pip install -e ".[dev,all]"

# 安装 AI 插件（可选）
pip install -e "./plugins/sqlseed-ai"

# 安装 MCP 服务器（可选）
pip install -e "./plugins/mcp-server-sqlseed"

# 运行测试
pytest

# 代码检查
ruff check src/ tests/

# 类型检查
mypy src/sqlseed/
```

## 常见任务

### 添加新的 Generator

1. 创建 `src/sqlseed/generators/new_provider.py`
2. 实现 `DataProvider` Protocol 的所有方法（`generators/_protocol.py`）
3. 通过 `ProviderRegistry.register()` 或 entry-points 注册
4. 在 `tests/test_generators/test_new_provider.py` 中添加测试

### 添加新的 Hook

1. 在 `src/sqlseed/plugins/hookspecs.py` 中添加 Hook 规范
2. 在 `orchestrator.py` 中的适当位置调用 Hook
3. 在 `tests/test_plugins/test_hookspecs.py` 中添加测试

### 添加新的 CLI 命令

1. 在 `src/sqlseed/cli/main.py` 中用 `@cli.command()` 装饰器添加命令函数
2. 使用 `click.testing.CliRunner` 在 `tests/test_cli.py` 中添加测试

## 重要文件

| 文件 | 用途 |
|------|------|
| `pyproject.toml` | 项目配置、依赖、entry-points |
| `src/sqlseed/__init__.py` | 公共 API 接口（`fill`、`connect`、`preview`、`fill_from_config`） |
| `src/sqlseed/core/orchestrator.py` | 核心编排引擎 |
| `src/sqlseed/core/mapper.py` | 列名 → 生成器策略映射（8 级链） |
| `src/sqlseed/core/column_dag.py` | [v2.0] 列依赖 DAG + 拓扑排序 |
| `src/sqlseed/core/expression.py` | [v2.0] 安全表达式引擎（simpleeval + 超时） |
| `src/sqlseed/core/constraints.py` | [v2.0] 约束求解器（唯一性、回溯） |
| `src/sqlseed/core/transform.py` | [v2.0] 用户 Transform 脚本加载器 |
| `src/sqlseed/core/relation.py` | [v2.0] FK 解析 + SharedPool |
| `src/sqlseed/core/schema.py` | Schema 推断（列、索引、样本数据） |
| `src/sqlseed/generators/_protocol.py` | DataProvider 接口契约 |
| `src/sqlseed/database/_protocol.py` | DatabaseAdapter 接口契约（ColumnInfo、ForeignKeyInfo、IndexInfo） |
| `src/sqlseed/plugins/hookspecs.py` | 所有插件 Hook 定义（10 个） |
| `plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py` | AI SchemaAnalyzer（LLM 集成） |
| `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py` | MCP 服务器工具 |

## 禁止事项

- 不要在核心包中添加对 `faker` 或 `mimesis` 的直接依赖 — 它们是可选的
- 不要直接使用 `import random` — 使用 Provider 的 `_rng` 实例以保证可复现性
- 不要绕过 `quote_identifier()` 工具处理 SQL 标识符
- 不要为 transform Hook 添加 `firstresult=True` — 它们必须支持链式处理
- 不要在层之间创建循环导入（core → generators → database 是依赖方向）
