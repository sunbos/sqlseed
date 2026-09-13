<div align="center">

# 🌱 sqlseed

**从已有表结构出发，为 SQLite 和 PostgreSQL 生成测试数据。**

[English](https://github.com/sunbos/sqlseed/blob/main/README.md) · [简体中文](https://github.com/sunbos/sqlseed/blob/main/README.zh-CN.md)

[![PyPI](https://img.shields.io/pypi/v/sqlseed.svg)](https://pypi.org/project/sqlseed/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/sunbos/sqlseed/actions/workflows/ci.yml/badge.svg)](https://github.com/sunbos/sqlseed/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](https://github.com/sunbos/sqlseed/blob/main/LICENSE)

[快速开始](#快速开始) · [Web 工作台](#web-工作台) · [命令行](#命令行) · [完整文档](https://sunbos.github.io/sqlseed/)

</div>

sqlseed 向已有数据库表中填充测试数据。它会为姓名、邮箱等常见字段推断生成规则；
对于业务需要的取值范围、候选值和字段关系，你可以通过 Python 或 YAML 明确指定。

- **准备开发和测试数据库：** 分批生成数据，协调受支持的外键依赖。
- **复用数据规则：** 保存配置、预览样例，并在相同条件下用 seed 复现生成结果。
- **选择使用入口：** Python API、终端、浏览器或 MCP 工具。Core 离线运行，AI 按需启用。

## 选择使用入口

需要 **Python 3.10+**。建议使用虚拟环境，按自己的使用方式安装对应包，
无需把下表中的包全部安装。各入口包会自动安装所需的 Core。

| 我想要…… | 安装命令 | 从这里开始 |
| --- | --- | --- |
| 在 Python 中生成数据 | `python -m pip install sqlseed` | [快速开始](#快速开始) |
| 在浏览器中操作 | `python -m pip install sqlseed-web` | [Web 工作台](#web-工作台) |
| 在终端中操作 | `python -m pip install sqlseed-cli` | [命令行](#命令行) |
| 让模型建议或修复规则 | `python -m pip install sqlseed-ai` | [可选的 AI 辅助](#可选的-ai-辅助) |
| 在 MCP 客户端中使用规则工具 | `python -m pip install mcp-server-sqlseed` | [MCP 配置](https://sunbos.github.io/sqlseed/guide/#mcp-server) |

Core 已包含 Faker，下面的示例会明确选择它。
Mimesis 是可选依赖，可通过 `python -m pip install 'sqlseed[mimesis]'` 安装。
旧版本用户请先看[升级指南](https://sunbos.github.io/sqlseed/migration.zh-CN/)。

## 快速开始

在你的 Python 环境中安装 Core：

```bash
python -m pip install sqlseed
```

在一个新目录中，将下面的代码保存为 `demo.py`，运行 `python demo.py`。
它会创建一张 SQLite 表并添加 100 个用户，无需克隆仓库、配置 API key 或启动数据库服务器。

```python
import sqlite3
from contextlib import closing

import sqlseed

with closing(sqlite3.connect("demo.db")) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL
        )
    """)
    conn.commit()

result = sqlseed.fill(
    "demo.db",
    table="users",
    count=100,
    provider="faker",
    seed=42,
)
print(result.count, result.errors)  # 100 []
```

姓名和邮箱的生成规则由字段名推断，主键由数据库分配。
每次运行会继续追加 100 行，不会清空表。生成后应同时检查 `result.count` 和 `result.errors`。

只想查看样例、不写入数据库时，可以使用：

```python
import sqlseed

rows = sqlseed.preview("demo.db", table="users", count=3, provider="faker")
for row in rows:
    print(row)
```

### 用 YAML 复用规则

针对同一个 `demo.db`，将下面的内容保存为 `generate.yaml`。
这里明确写出各列的生成器，便于审阅和复用：

```yaml
db_path: demo.db
provider: faker
locale: en_US
tables:
  - name: users
    count: 100
    seed: 42
    columns:
      - name: name
        generator: name
      - name: email
        generator: email
```

在同一目录中执行：

```python
import sqlseed

for result in sqlseed.fill_from_config("generate.yaml"):
    print(result.count, result.errors)
```

[配置指南](https://sunbos.github.io/sqlseed/guide/#yaml-configuration)介绍了取值范围、
加权选择、派生列和跨表关系；完整名称与参数见[生成器参考](https://sunbos.github.io/sqlseed/guide/#generators)。

## Web 工作台

```bash
python -m pip install sqlseed-web
sqlseed-web
```

打开 **[http://127.0.0.1:8630](http://127.0.0.1:8630)**，连接已有数据库
（例如上面创建的 `demo.db`），选择表、编辑规则、预览，再生成数据。
`sqlseed-web` 命令随安装包提供，不需要自定义启动脚本，也不需要仓库源码。

工作台还提供配置保存、关系图和运行记录。AI 为可选功能，未安装时仍可手动编辑、预览和生成。
连接设置、可选组件与部署要求见 [Web 使用指南](https://sunbos.github.io/sqlseed/web-workbench/)。

## 命令行

安装 CLI 后，可以直接操作快速开始中创建的数据库：

```bash
python -m pip install sqlseed-cli
sqlseed inspect demo.db --table users --show-mapping
sqlseed preview demo.db -t users -n 5 --provider faker
sqlseed fill demo.db -t users -n 100 --provider faker --no-ai
```

运行 `sqlseed --help` 或 `sqlseed <命令> --help` 查看选项。
配置模板、快照和重放的用法见 [CLI 参考](https://sunbos.github.io/sqlseed/guide/#cli-reference)。
只安装 Core 时提供 Python API，`sqlseed` 命令由 `sqlseed-cli` 包提供。

## PostgreSQL

安装 PostgreSQL 驱动扩展：

```bash
python -m pip install 'sqlseed[postgres]'
```

准备好数据库和表后，通过 `url` 明确传入连接地址：

```python
import sqlseed

result = sqlseed.fill(
    url="postgresql+psycopg://user:password@localhost:5432/app",
    table="users",
    count=100,
    provider="faker",
)
print(result.count, result.errors)
```

SQLite 路径与 `url` 不能同时传入。支持的外键结构和各入口差异见
[支持范围](https://sunbos.github.io/sqlseed/maintainable-release/)。

## 可选的 AI 辅助

`sqlseed-ai` 提供规则建议和配置修复命令。安装后，按照
[AI 配置指南](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/README.zh-CN.md)连接模型服务。

| 命令 | 用途 |
| --- | --- |
| `sqlseed ai-suggest` | 为单张表建议生成规则 |
| `sqlseed ai-analyze` | 分析所选表或整个数据库 |
| `sqlseed auto-heal` | 修复已有、结构合法的 YAML 配置中的规则 |

分析与修复流程可以为已支持的 CHECK 模式推断规则，例如枚举、范围和跨列关系。
其他约束可能需要显式配置或模型建议，不能把它理解为任意 SQL CHECK 的求解器。
使用候选配置前，仍需审阅规则并验证实际生成的数据。

具体用法见 [AI 命令参考](https://sunbos.github.io/sqlseed/guide/#ai-suggest)和
[模型后端与校验说明](https://sunbos.github.io/sqlseed/gemma4-integration.zh-CN/)。
如需模型辅助的 MCP 工具，使用 `sqlseed-ai[mcp]` 提供的独立服务；
[MCP 配置](https://sunbos.github.io/sqlseed/guide/#mcp-server)说明了两种服务的区别。

## 用于自己的数据库时

- **先建表。** sqlseed 读取已有结构；必需的父表记录应已存在，或在配置中安排先生成。
- **检查执行结果。** Core 或 CLI 生成失败时，之前已经提交的批次可能保留。重试前先检查 `count` 和 `errors`。
- **保持复现条件一致。** 只有 seed 相同，并不能保证跨依赖版本、provider、配置或初始数据得到完全相同的结果。

复杂 CHECK 和复合外键的支持范围因数据库而异，具体边界与写入行为见
[支持与维护说明](https://sunbos.github.io/sqlseed/maintainable-release/)。

## 文档导航

| 下一步 | 文档 |
| --- | --- |
| 配置生成器、表达式与多表数据 | [用户指南](https://sunbos.github.io/sqlseed/guide/) |
| 使用 `fill`、`preview`、`connect`、`fill_from_config`、`load_config` | [Python API 参考](https://sunbos.github.io/sqlseed/api/) |
| 跑通完整的多表示例 | [订单工作流](https://github.com/sunbos/sqlseed/tree/main/examples/order_workflow) |
| 了解包边界和扩展 hooks | [架构文档](https://sunbos.github.io/sqlseed/architecture.zh-CN/) |
| 升级已有安装 | [迁移指南](https://sunbos.github.io/sqlseed/migration.zh-CN/) |
| 查看已发布版本与变更 | [Releases](https://github.com/sunbos/sqlseed/releases) |

## 参与开发

源码安装、开发检查和贡献方式见 [CONTRIBUTING.md](https://github.com/sunbos/sqlseed/blob/main/CONTRIBUTING.md)。
反馈问题时，请在 [GitHub Issues](https://github.com/sunbos/sqlseed/issues) 中提供最小表结构、
生成配置、包版本和完整错误信息。

## 许可证

[AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE)。
