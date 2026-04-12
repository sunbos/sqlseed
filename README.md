# sqlseed

> **Declarative SQLite Test Data Generation Toolkit**

用最少的代码，为数据库表智能生成大量高质量测试数据。

[![CI](https://github.com/your-org/sqlseed/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/sqlseed/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)

## ✨ 特性

- 🚀 **零配置智能生成** — 自动推断 Schema，自动选择生成策略，一行代码搞定
- 🎯 **声明式配置** — 通过 Python API 或 YAML/JSON 配置精确控制数据生成
- 🔌 **多种 Provider** — 支持 Mimesis（默认推荐）、Faker 等高性能数据生成引擎
- 🧠 **智能列映射** — 8 级策略链：精确匹配 → 模式匹配 → 类型回退 → 默认
- 🔗 **外键支持** — 自动维持引用完整性，拓扑排序处理依赖关系
- 📊 **批量优化** — SQLite PRAGMA 三级优化策略（LIGHT / MODERATE / AGGRESSIVE）
- 🌊 **流式处理** — 内存占用恒定，与总数据量无关
- 🧩 **插件系统** — 基于 pluggy 的可扩展架构，9 个 Hook 点覆盖全生命周期
- 🤖 **AI 就绪** — `sqlseed-ai` 一等公民插件，LLM 驱动的智能数据生成
- 🖥️ **CLI 命令行** — 完整的命令行工具支持（fill / preview / inspect / init / replay）
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

# 预览生成的数据（不写入）
sqlseed preview test.db --table users --count 5

# 查看数据库表信息
sqlseed inspect test.db

# 查看特定表的列映射策略
sqlseed inspect test.db --table users --show-mapping

# 使用 YAML 配置
sqlseed fill --config generate.yaml

# 生成配置模板
sqlseed init generate.yaml --db test.db

# 保存生成快照
sqlseed fill test.db --table users --count 10000 --seed 42 --snapshot

# 回放快照
sqlseed replay snapshots/2026-04-12_users.yaml
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
│   ├── orchestrator.py      # DataOrchestrator 主编排引擎
│   ├── schema.py            # SchemaInferrer - 从 DB 推断列信息
│   ├── mapper.py            # ColumnMapper - 列名→生成策略多级映射
│   ├── relation.py          # RelationResolver - 外键关系解析与拓扑排序
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
│   ├── _protocol.py         # DatabaseAdapter Protocol 定义
│   ├── sqlite_utils_adapter.py   # sqlite-utils 适配器
│   ├── raw_sqlite_adapter.py     # sqlite3 回退适配器
│   └── optimizer.py         # PragmaOptimizer - PRAGMA 智能优化
│
├── plugins/                 # ===== 插件层 =====
│   ├── hookspecs.py         # pluggy Hook 规范定义
│   └── manager.py           # PluginManager 管理器
│
├── config/                  # ===== 配置管理 =====
│   ├── models.py            # Pydantic 配置模型
│   ├── loader.py            # YAML/JSON 配置文件加载
│   └── snapshot.py          # 配置快照保存与回放
│
├── cli/                     # ===== 命令行接口 =====
│   └── main.py              # click CLI 入口
│
└── _utils/                  # ===== 内部工具 =====
    ├── sql_safe.py          # SQL 标识符安全转义
    ├── schema_helpers.py    # 共享 Schema 辅助函数
    ├── metrics.py           # 性能度量收集
    ├── progress.py          # rich 进度条封装
    └── logger.py            # structlog 日志封装
```

## 🧩 插件系统

sqlseed 通过 [pluggy](https://pluggy.readthedocs.io/) 提供完整的插件扩展能力，9 个 Hook 点覆盖数据生成全生命周期：

| Hook | 说明 |
|------|------|
| `sqlseed_register_providers` | 注册自定义 Provider |
| `sqlseed_register_column_mappers` | 注册自定义列映射规则 |
| `sqlseed_ai_suggest_generator` | AI 智能列映射推荐 |
| `sqlseed_before_generate` | 数据生成前钩子 |
| `sqlseed_after_generate` | 数据生成后钩子 |
| `sqlseed_transform_row` | 行级转换 |
| `sqlseed_transform_batch` | 批次级转换（支持链式处理） |
| `sqlseed_before_insert` | 批次插入前钩子 |
| `sqlseed_after_insert` | 批次插入后钩子 |

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

## 📊 测试

- **286 个测试** 全部通过
- **98% 测试覆盖率**
- 测试策略：单元测试 + 集成测试 + CLI 测试 + 快照测试

## 📄 License

[AGPL v3](LICENSE)
