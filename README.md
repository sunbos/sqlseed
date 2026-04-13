# sqlseed

> **声明式 SQLite 测试数据生成工具包**

用最少的代码，为数据库表智能生成大量高质量测试数据。

[![CI](https://github.com/your-org/sqlseed/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/sqlseed/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

## ✨ 特性

- 🚀 **零配置智能生成** — 自动推断 Schema，自动选择生成策略，一行代码搞定
- 🎯 **声明式配置** — 通过 Python API 或 YAML/JSON 配置精确控制数据生成
- 🔌 **多种 Provider** — 支持 Mimesis（默认推荐）、Faker 等高性能数据生成引擎
- 🧠 **智能列映射** — 8 级策略链：精确匹配 → 模式匹配 → 类型回退 → 默认
- 🔗 **外键支持** — 自动维持引用完整性，拓扑排序处理依赖关系
- 📊 **批量优化** — SQLite PRAGMA 三级优化策略（LIGHT / MODERATE / AGGRESSIVE）
- 🌊 **流式处理** — 内存占用恒定，与总数据量无关
- 🧩 **插件系统** — 基于 pluggy 的可扩展架构，10 个 Hook 点覆盖全生命周期
- 🤖 **AI 就绪** — `sqlseed-ai` 一等公民插件，LLM 驱动的智能数据生成
- 🔗 **MCP 集成** — `mcp-server-sqlseed` 通过 Model Context Protocol 与 AI 助手交互
- 🧮 **表达式引擎** — 安全的派生列计算，支持超时保护和回溯约束求解
- 🖥️ **CLI 命令行** — 完整的命令行工具支持（fill / preview / inspect / init / replay / ai-suggest）
- 📸 **快照回放** — 保存生成配置快照，随时精确回放

## 📦 安装

```bash
# 核心安装
pip install sqlseed

# 推荐：使用高性能 Mimesis
pip install sqlseed[mimesis]

# 使用 Faker
pip install sqlseed[faker]

# 安装全部 Provider
pip install sqlseed[all]

# 开发安装
pip install -e ".[dev,all]"

# AI 插件（可选）
pip install -e "./plugins/sqlseed-ai"

# MCP 服务器（可选）
pip install -e "./plugins/mcp-server-sqlseed"
```

## 🚀 快速开始

### 模式 1: 极简一行代码

```python
import sqlseed

# 自动推断 Schema，自动选择生成策略，零配置
sqlseed.fill("test.db", table="users", count=10000)
```

### 模式 2: 声明式配置

```python
sqlseed.fill(
    "test.db",
    table="users",
    count=100000,
    columns={
        "email": "email",                             # 简写：直接指定生成器名称
        "age": {"type": "integer", "min_value": 18, "max_value": 65},
        "bio": {"type": "text", "max_length": 200},
        "status": {"type": "choice", "choices": [0, 1, 2]},
    },
    provider="mimesis",
    locale="zh_CN",
    seed=42,              # 种子控制，确保可重复
    clear_before=True,    # 生成前清空表
)
```

### 模式 3: 上下文管理器（多表 + 外键）

```python
with sqlseed.connect("test.db") as db:
    # 先填充父表
    db.fill("users", count=10000, seed=42)

    # 再填充子表，自动维持外键关联
    db.fill("orders", count=50000, columns={
        "user_id": {
            "type": "foreign_key",
            "ref_table": "users",
            "ref_column": "id",
            "strategy": "random",
        },
        "amount": {"type": "float", "min": 9.99, "max": 999.99},
        "created_at": "datetime",
    })

    # 查看生成报告
    report = db.report()
    print(report)
```

### 模式 4: YAML 配置文件驱动

```python
sqlseed.fill_from_config("generate.yaml")
```

### 模式 5: 预览（不写入数据库）

```python
preview = sqlseed.preview("test.db", table="users", count=5)
for row in preview:
    print(row)
```

## 🖥️ CLI 使用

```bash
# 零配置填充
sqlseed fill test.db --table users --count 10000

# 指定 Provider 和地区
sqlseed fill test.db --table users --count 10000 --provider mimesis --locale zh_CN

# 使用种子确保可重复
sqlseed fill test.db --table users --count 10000 --seed 42

# 生成前清空表
sqlseed fill test.db --table users --count 10000 --clear

# 使用 YAML 配置
sqlseed fill --config generate.yaml

# 预览生成的数据（不写入）
sqlseed preview test.db --table users --count 5

# 查看数据库表信息
sqlseed inspect test.db

# 查看特定表的列映射策略
sqlseed inspect test.db --table users --show-mapping

# 生成配置模板
sqlseed init generate.yaml --db test.db

# 保存生成快照
sqlseed fill test.db --table users --count 10000 --seed 42 --snapshot

# 回放快照
sqlseed replay snapshots/2026-04-12_users.yaml

# AI 智能建议（需要安装 sqlseed-ai 插件）
sqlseed ai-suggest test.db --table users --output users.yaml
sqlseed ai-suggest test.db --table users --output users.yaml --model gpt-4o
```

## 📝 YAML 配置文件

```yaml
# generate.yaml
db_path: "test.db"
provider: mimesis
locale: zh_CN
optimize_pragma: true
log_level: INFO
snapshot_dir: "./snapshots"

tables:
  - name: users
    count: 100000
    clear_before: true
    seed: 42
    columns:
      - name: username
        generator: name
      - name: email
        generator: email
      - name: phone
        generator: phone
      - name: age
        generator: integer
        params:
          min_value: 18
          max_value: 65
      - name: status
        generator: choice
        params:
          choices: [0, 1, 2]
        null_ratio: 0.05

  - name: orders
    count: 500000
    batch_size: 10000
    columns:
      - name: user_id
        generator: foreign_key
        params:
          ref_table: users
          ref_column: id
          strategy: random
      - name: amount
        generator: float
        params:
          min_value: 1.0
          max_value: 9999.99
          precision: 2
```

使用配置文件：
```bash
sqlseed fill --config generate.yaml
```

## 🏗️ 项目架构

```
src/sqlseed/
├── __init__.py              # 公共 API (fill, connect, fill_from_config, preview)
├── py.typed                 # PEP 561 类型标记
├── _version.py              # 版本号
│
├── core/                    # ===== 核心编排层 =====
│   ├── orchestrator.py      # DataOrchestrator 主编排引擎 (SharedPool + AI hook)
│   ├── schema.py            # SchemaInferrer - 从 DB 推断列信息、索引、样本数据
│   ├── mapper.py            # ColumnMapper - 列名→生成策略多级映射
│   ├── relation.py          # RelationResolver + SharedPool - 外键解析与跨表共享池
│   ├── column_dag.py        # [v2.0] ColumnDAG - 列依赖 DAG + 拓扑排序
│   ├── expression.py        # [v2.0] ExpressionEngine - 安全表达式引擎 (simpleeval + 超时)
│   ├── constraints.py       # [v2.0] ConstraintSolver - 唯一性约束回溯求解
│   ├── transform.py         # [v2.0] TransformLoader - 用户脚本动态加载
│   └── result.py            # GenerationResult 数据类
│
├── generators/              # ===== 数据生成层 =====
│   ├── _protocol.py         # DataProvider Protocol 定义
│   ├── registry.py          # ProviderRegistry 注册表
│   ├── base_provider.py     # 内置基础生成器（无外部依赖）
│   ├── faker_provider.py    # Faker 适配器
│   ├── mimesis_provider.py  # Mimesis 适配器
│   └── stream.py            # 流式数据生成器
│
├── database/                # ===== 数据库层 =====
│   ├── _protocol.py         # DatabaseAdapter Protocol (ColumnInfo, ForeignKeyInfo, IndexInfo)
│   ├── sqlite_utils_adapter.py   # sqlite-utils 适配器
│   ├── raw_sqlite_adapter.py     # sqlite3 回退适配器
│   └── optimizer.py         # PragmaOptimizer - PRAGMA 智能优化
│
├── plugins/                 # ===== 插件层 =====
│   ├── hookspecs.py         # pluggy Hook 规范定义 (10 hooks)
│   └── manager.py           # PluginManager 管理器
│
├── config/                  # ===== 配置管理 =====
│   ├── models.py            # Pydantic 配置模型
│   ├── loader.py            # YAML/JSON 配置文件加载
│   └── snapshot.py          # 配置快照保存与回放
│
├── cli/                     # ===== 命令行接口 =====
│   └── main.py              # click CLI 入口 (fill, preview, inspect, init, replay, ai-suggest)
│
└── _utils/                  # ===== 内部工具 =====
    ├── sql_safe.py          # SQL 标识符安全转义
    ├── schema_helpers.py    # 共享 Schema 辅助函数
    ├── metrics.py           # 性能度量收集
    ├── progress.py          # rich 进度条封装
    └── logger.py            # structlog 日志封装

plugins/
├── sqlseed-ai/              # ===== AI 插件 =====
│   └── src/sqlseed_ai/
│       ├── analyzer.py      # SchemaAnalyzer - LLM 集成 + 上下文嗅探
│       ├── suggest.py       # AI 建议生成
│       ├── nl_config.py     # 自然语言配置
│       ├── provider.py      # AI Provider
│       ├── config.py        # AIConfig 配置模型
│       └── _client.py       # LLM 客户端封装
│
└── mcp-server-sqlseed/      # ===== MCP 服务器 =====
    └── src/mcp_server_sqlseed/
        ├── server.py        # FastMCP 工具 (inspect_schema, generate_yaml, execute_fill)
        ├── config.py        # MCP 配置
        ├── __init__.py      # 包入口
        └── __main__.py      # CLI 入口 (python -m mcp_server_sqlseed)
```

## 🧩 插件系统

sqlseed 通过 [pluggy](https://pluggy.readthedocs.io/) 提供完整的插件扩展能力，10 个 Hook 点覆盖数据生成全生命周期：

| Hook | 说明 |
|------|------|
| `sqlseed_register_providers` | 注册自定义 Provider |
| `sqlseed_register_column_mappers` | 注册自定义列映射规则 |
| `sqlseed_ai_analyze_table` | AI 智能表分析（firstresult） |
| `sqlseed_before_generate` | 数据生成前钩子 |
| `sqlseed_after_generate` | 数据生成后钩子 |
| `sqlseed_transform_row` | 行级转换 |
| `sqlseed_transform_batch` | 批次级转换（支持链式处理） |
| `sqlseed_before_insert` | 批次插入前钩子 |
| `sqlseed_after_insert` | 批次插入后钩子 |
| `sqlseed_shared_pool_loaded` | 跨表共享池加载完成钩子 |

## 🔗 MCP 服务器

`mcp-server-sqlseed` 提供三个 MCP 工具，允许 AI 助手（如 Claude、Cursor）直接与 sqlseed 交互：

| 工具 | 说明 |
|------|------|
| `sqlseed_inspect_schema` | 检查数据库 Schema（列、外键、索引、样本数据） |
| `sqlseed_generate_yaml` | AI 驱动的 YAML 配置生成 |
| `sqlseed_execute_fill` | 执行数据生成（支持 YAML 配置） |

```bash
# 启动 MCP 服务器
python -m mcp_server_sqlseed
```

## 🛠️ 开发

```bash
# 克隆项目
git clone https://github.com/your-org/sqlseed.git
cd sqlseed

# 安装开发依赖
pip install -e ".[dev,all]"

# 运行测试
pytest

# 代码检查
ruff check src/ tests/

# 类型检查
mypy src/sqlseed/
```

## 📄 License

[AGPL v3](LICENSE)
