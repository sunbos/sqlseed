<div align="center">

# 🌱 sqlseed

### 声明式 SQLite 测试数据生成工具包

**一行代码，数万行数据。零配置智能生成，AI 驱动精准调优。**

[![CI](https://github.com/sunbos/sqlseed/actions/workflows/ci.yml/badge.svg)](https://github.com/sunbos/sqlseed/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab.svg?logo=python\&logoColor=white)](https://www.python.org/downloads/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type: mypy](https://img.shields.io/badge/type%20checker-mypy-blue.svg)](https://mypy-lang.org/)

</div>

***

```python
import sqlseed

# 就这一行。自动推断 Schema，自动选择策略，自动优化写入。
result = sqlseed.fill("test.db", table="users", count=100_000)
print(result)
# → GenerationResult(table=users, count=100000, elapsed=2.34s, speed=42735 rows/s)
```

***

## 💡 为什么选择 sqlseed？

在开发和测试流程中，我们经常需要为 SQLite 数据库填充大量真实感的测试数据。传统方式要么手写冗长的数据生成脚本，要么使用难以维护的 SQL fixtures。sqlseed 用一种全新的声明式方式解决了这个问题：

| 特性         | sqlseed |  手写脚本  | SQL Fixtures |
| :--------- | :-----: | :----: | :----------: |
| 零配置智能生成    |    ✅    |    ❌   |       ❌      |
| 外键自动维护     |    ✅    |   手动   |      手动      |
| 10 万行 + 数据 |   ✅ 流式  | ⚠️ OOM |       ❌      |
| 列语义推断      | ✅ 9 级策略 |    ❌   |       ❌      |
| 可重复生成      |  ✅ seed |  ⚠️ 手动 |       ✅      |
| AI 智能调优    |  ✅ LLM  |    ❌   |       ❌      |
| 配置热重用      |  ✅ YAML |    ❌   |       ❌      |

## ✨ 核心特性

<table>
<tr>
<td width="50%">

**🚀 零配置智能生成**

自动推断数据库 Schema，通过 9 级策略链为每列选择最佳生成器。列名是 `email`？生成邮箱。列名是 `*_at`？生成时间戳。完全不需要配置。

</td>
<td width="50%">

**🎯 声明式精确控制**

通过 Python API 或 YAML/JSON 配置精确控制每一列的数据生成策略、约束条件和空值比率。

</td>
</tr>
<tr>
<td>

**🔗 外键自动排序**

拓扑排序自动检测表依赖关系，SharedPool 跨表共享值池，零配置维持引用完整性。

</td>
<td>

**🌊 流式内存安全**

`DataStream` 通过 `Iterator[list[dict]]` 逐批 yield，100 万行数据内存占用与 1000 行相同。

</td>
</tr>
<tr>
<td>

**🧮 表达式引擎 & 约束求解**

支持派生列计算（`last_eight = card_number[-8:]`），唯一性约束回溯求解，超时保护防止死循环。

</td>
<td>

**🤖 AI 一等公民**

`sqlseed-ai` 插件通过 LLM 分析 Schema 语义，自动生成 YAML 配置建议，支持自纠正闭环。

</td>
</tr>
<tr>
<td>

**🧩 11 个 Hook 全生命周期**

基于 pluggy 的插件架构，从 Provider 注册到批次插入，覆盖数据生成的每个环节。

</td>
<td>

**📊 三级 PRAGMA 优化**

根据数据量智能切换 LIGHT / MODERATE / AGGRESSIVE 三种写入策略，最大化吞吐量。

</td>
</tr>
</table>

***

## 📦 安装

### 基础安装

```bash
pip install sqlseed
```

### 选择数据引擎

```bash
# 推荐：Mimesis（高性能，本地化支持好）
pip install sqlseed[mimesis]

# 可选：Faker（生态丰富）
pip install sqlseed[faker]

# 全部安装
pip install sqlseed[all]
```

### 可选插件

```bash
# AI 智能分析插件（LLM 驱动）
pip install sqlseed-ai

# MCP 服务器（让 AI 助手直接操作 sqlseed）
pip install mcp-server-sqlseed
```

<details>
<summary><b>📋 开发环境完整安装</b></summary>

```bash
git clone https://github.com/sunbos/sqlseed.git
cd sqlseed

# 安装核心 + 所有 Provider + 开发依赖
pip install -e ".[dev,all]"

# 可选插件
pip install -e "./plugins/sqlseed-ai"
pip install -e "./plugins/mcp-server-sqlseed"

# 验证安装
pytest
ruff check src/ tests/
mypy src/sqlseed/
```

</details>

***

## 🚀 快速开始

### 30 秒上手

假设你有一个 SQLite 数据库 `app.db`，其中有一张 `users` 表：

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    age INTEGER,
    phone TEXT,
    created_at TEXT,
    is_active INTEGER DEFAULT 1,
    balance REAL
);
```

只需一行代码即可填充 1 万行高质量测试数据：

```python
import sqlseed

result = sqlseed.fill("app.db", table="users", count=10_000)
print(result)
# → GenerationResult(table=users, count=10000, elapsed=0.52s, speed=19230 rows/s)
```

sqlseed 会自动：

- ✅ 跳过 `id`（自增主键）
- ✅ 跳过 `is_active`（有默认值）
- ✅ `name` → 生成真实姓名
- ✅ `email` → 生成邮箱地址
- ✅ `age` → 生成 18\~100 的整数
- ✅ `phone` → 生成电话号码
- ✅ `created_at` → 生成日期时间（匹配 `*_at` 模式）
- ✅ `balance` → 生成浮点数

**完全零配置，智能推断一切。**

***

## 📖 使用教程

### 教程 1：Python API — 精确控制每一列

当你需要对数据有更精细的控制时，可以通过 `columns` 参数声明每列的生成策略：

```python
import sqlseed

result = sqlseed.fill(
    "app.db",
    table="users",
    count=50_000,
    columns={
        # 简写：直接指定生成器名
        "email": "email",
        "phone": "phone",
        
        # 完整配置：指定参数
        "age": {"type": "integer", "min_value": 18, "max_value": 65},
        "balance": {"type": "float", "min_value": 0.0, "max_value": 100000.0, "precision": 2},
        "name": "name",
        
        # 从候选列表中随机选择
        "status": {"type": "choice", "choices": ["active", "inactive", "banned"]},
    },
    provider="mimesis",      # 使用 Mimesis 引擎
    locale="zh_CN",          # 中文地区
    seed=42,                 # 固定种子，确保结果可重复
    clear_before=True,       # 生成前清空表
    enrich=True,             # 从现有数据推断分布（如枚举列、值范围）
    transform="./transform_users.py",  # 每行生成后执行自定义变换
)
print(result)
```

#### 支持的生成器类型

| 生成器           | 说明             | 参数示例                                  |
| :------------ | :------------- | :------------------------------------ |
| `string`      | 随机字符串          | `min_length`, `max_length`, `charset` |
| `integer`     | 整数             | `min_value`, `max_value`              |
| `float`       | 浮点数            | `min_value`, `max_value`, `precision` |
| `boolean`     | 布尔值            | —                                     |
| `name`        | 人名             | —                                     |
| `first_name`  | 名              | —                                     |
| `last_name`   | 姓              | —                                     |
| `email`       | 邮箱             | —                                     |
| `phone`       | 电话             | —                                     |
| `address`     | 地址             | —                                     |
| `company`     | 公司名            | —                                     |
| `url`         | URL            | —                                     |
| `ipv4`        | IPv4 地址        | —                                     |
| `uuid`        | UUID           | —                                     |
| `date`        | 日期             | `start_year`, `end_year`              |
| `datetime`    | 日期时间           | `start_year`, `end_year`              |
| `timestamp`   | Unix 时间戳       | —                                     |
| `text`        | 长文本            | `min_length`, `max_length`            |
| `sentence`    | 句子             | —                                     |
| `password`    | 密码             | `length`                              |
| `choice`      | 从列表选择          | `choices`                             |
| `json`        | JSON 字符串       | `schema`                              |
| `pattern`     | 正则匹配           | `regex`                               |
| `bytes`       | 二进制数据          | `length`                              |
| `foreign_key` | 外键引用           | `ref_table`, `ref_column`, `strategy` |
| `skip`        | 跳过（使用默认值/NULL） | —                                     |

***

### 教程 2：多表关联 — 自动维持外键完整性

使用上下文管理器模式可以处理跨表数据依赖：

```python
import sqlseed

with sqlseed.connect("app.db", provider="mimesis", locale="zh_CN") as db:
    # 步骤 1：先填充父表
    db.fill("users", count=10_000, seed=42)
    
    # 步骤 2：填充子表 — sqlseed 自动检测外键约束，
    #         从 users.id 中随机选取值填入 orders.user_id
    db.fill("orders", count=50_000, columns={
        "amount": {"type": "float", "min_value": 9.99, "max_value": 999.99, "precision": 2},
        "quantity": {"type": "integer", "min_value": 1, "max_value": 20},
        "status": {"type": "choice", "choices": ["pending", "paid", "shipped", "delivered"]},
    })
    
    # 步骤 3：查看生成报告
    print(db.report())
    # → Database: app.db
    # → ==================================================
    # →   users: 10000 rows
    # →   orders: 50000 rows
```

> **💡 提示**：如果两张表之间有同名列（如 `account_id`），即使没有声明外键约束，sqlseed 也会通过 **SharedPool 隐式关联机制**自动维持跨表一致性。

#### 显式跨表关联（ColumnAssociation）

当目标列名与源列名不同（如 `department_id` → `id`），或没有 FK 约束但需要关联时，可以通过 `associations` 配置显式声明：

```yaml
db_path: "app.db"
provider: mimesis

tables:
  - name: departments
    count: 5
    clear_before: true
  - name: employees
    count: 20
    clear_before: true

associations:
  - column_name: department_id     # 目标表中的列名
    source_table: departments      # 提供值的源表
    source_column: id              # 源表中的列名（默认等于 column_name）
    target_tables:                 # 使用此关联的目标表列表
      - employees
    strategy: shared_pool          # 关联策略
```

这样即使 `employees` 表没有 `FOREIGN KEY (department_id) REFERENCES departments(id)` 约束，`department_id` 的值也会来自 `departments.id`。

***

### 教程 3：YAML 配置文件驱动批量生成

对于复杂的多表场景，推荐使用 YAML 配置文件：

**1. 生成配置模板**

```bash
sqlseed init generate.yaml --db app.db
```

**2. 编辑配置文件**

```yaml
# generate.yaml
db_path: "app.db"
provider: mimesis
locale: zh_CN
optimize_pragma: true

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
        null_ratio: 0.05       # 5% 概率为 NULL

  - name: orders
    count: 500000
    batch_size: 10000          # 每批 1 万行，优化内存
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
      - name: created_at
        generator: datetime
        params:
          start_year: 2024
```

**3. 执行生成**

```bash
sqlseed fill --config generate.yaml
```

或在 Python 中：

```python
results = sqlseed.fill_from_config("generate.yaml")
for r in results:
    print(r)
```

***

### 教程 4：派生列与表达式引擎

sqlseed v2.0 引入了列依赖 DAG 和表达式引擎，支持从已有列计算派生列：

```yaml
# 银行卡信息表场景
tables:
  - name: bank_cards
    count: 10000
    columns:
      - name: card_number
        generator: pattern
        params:
          regex: "62[0-9]{17}"     # 19 位银联卡号
        constraints:
          unique: true

      - name: last_eight
        derive_from: card_number       # 依赖 card_number
        expression: "value[-8:]"   # 取后 8 位
        constraints:
          unique: true

      - name: last_six
        derive_from: card_number
        expression: "value[-6:]"   # 取后 6 位

      - name: account_id
        generator: pattern
        params:
          regex: "U[0-9]{10}"
        constraints:
          unique: true
```

**运作原理**：

1. sqlseed 构建列依赖 DAG：`card_number → last_eight, last_six`
2. 拓扑排序确定生成顺序
3. 先生成 `card_number`，再通过表达式 `value[-8:]` 计算 `last_eight`
4. 如果 `last_eight` 的唯一性约束失败，回溯重新生成 `card_number`

#### 表达式引擎支持的函数

| 函数                      | 用法                        | 说明          |
| :---------------------- | :------------------------ | :---------- |
| `upper(s)`              | `upper(value)`            | 转大写         |
| `lower(s)`              | `lower(value)`            | 转小写         |
| `len(s)`                | `len(value)`              | 获取长度        |
| `substr(s, start, end)` | `substr(value, 0, 8)`     | 子串          |
| `concat(*args)`         | `concat("PRE_", value)`   | 拼接          |
| `zfill(s, width)`       | `zfill(value, 10)`        | 零填充         |
| `lpad(s, width, char)`  | `lpad(value, 8, "0")`     | 左填充         |
| `rpad(s, width, char)`  | `rpad(value, 8, "0")`     | 右填充         |
| `replace(s, old, new)`  | `replace(value, "-", "")` | 替换          |
| `strip(s)`              | `strip(value)`            | 去空白         |
| `int(s)`                | `int(value)`              | 转整数         |
| `str(s)`                | `str(value)`              | 转字符串        |
| 切片                      | `value[-8:]`              | Python 切片语法 |
| 数学                      | `value * 2 + 1`           | 基本数学运算      |

> ⚠️ **安全保护**：表达式引擎基于 `simpleeval`，具有 5 秒超时保护，不允许 `import`、`exec` 或文件 I/O 操作。

***

### 教程 5：Transform 脚本 — 极端业务逻辑

对于无法用声明式配置表达的复杂业务逻辑，可以编写 Python 变换脚本：

**1. 编写 transform 脚本**

```python
# transform_users.py
def transform_row(row, ctx):
    """每一行生成后都会经过此函数处理。"""
    
    # 根据年龄计算 VIP 等级
    age = row.get("age", 0)
    if age >= 60:
        row["vip_level"] = 3
    elif age >= 40:
        row["vip_level"] = 2
    else:
        row["vip_level"] = 1
    
    # 标准化手机号格式
    phone = row.get("phone", "")
    if phone and not phone.startswith("+86"):
        row["phone"] = f"+86{phone}"
    
    return row
```

**2. 在 CLI 中使用**

```bash
sqlseed fill app.db --table users --count 10000 --transform transform_users.py
```

**3. 在 YAML 中使用**

```yaml
tables:
  - name: users
    count: 10000
    transform: "./transform_users.py"
```

***

### 教程 6：预览与调试

在大量生成数据前，先预览看看效果：

**Python API：**

```python
rows = sqlseed.preview("app.db", table="users", count=5, seed=42)
# 也可以使用 enrich 和 transform 参数
rows = sqlseed.preview("app.db", table="users", count=5, seed=42, enrich=True)
for row in rows:
    print(row)
# → {'name': '张伟', 'email': 'zhangwei@example.com', 'age': 32, ...}
# → {'name': '李娜', 'email': 'lina@test.org', 'age': 28, ...}
# → ...
```

**CLI（Rich 表格输出）：**

```bash
sqlseed preview app.db --table users --count 5

# ┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
# ┃ name    ┃ email               ┃ age ┃ created_at          ┃
# ┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
# │ 张伟     │ zhangwei@example.com│ 32  │ 2024-03-15 08:23:11 │
# │ ...     │ ...                 │ ... │ ...                 │
# └─────────┴─────────────────────┴─────┴─────────────────────┘
```

**查看列映射策略：**

```bash
sqlseed inspect app.db --table users --show-mapping

# 查看 sqlseed 为每一列选择了什么生成策略
# ┏━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
# ┃ Column     ┃ Type    ┃ Nullable ┃ Generator    ┃ Params       ┃
# ┡━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
# │ id         │ INTEGER │ ✗        │ skip         │ {}           │
# │ name       │ TEXT    │ ✗        │ name         │ {}           │
# │ email      │ TEXT    │ ✓        │ email        │ {}           │
# │ age        │ INTEGER │ ✓        │ integer      │ {min: 18...} │
# │ ...        │ ...     │ ...      │ ...          │ ...          │
# └────────────┴─────────┴──────────┴──────────────┴──────────────┘
```

***

### 教程 7：快照与回放

保存一次成功的生成配置，以后随时精确回放：

```bash
# 生成并保存快照
sqlseed fill app.db --table users --count 10000 --seed 42 --snapshot
# → Snapshot saved: snapshots/2026-04-15_033000_users.yaml

# 任意时刻回放
sqlseed replay snapshots/2026-04-15_033000_users.yaml
# → GenerationResult(table=users, count=10000, elapsed=0.52s, speed=19230 rows/s)
```

适用场景：

- 🧪 CI/CD 中需要可重复的测试数据
- 📋 团队间共享一致的测试环境
- 🔄 开发时快速重建数据库状态

***

### 教程 8：AI 智能配置（sqlseed-ai 插件）

让 LLM 分析你的数据库 Schema，自动生成最佳配置建议：

```bash
# 安装 AI 插件
pip install sqlseed-ai

# 设置 API Key
export SQLSEED_AI_API_KEY="your-api-key"
export SQLSEED_AI_BASE_URL="https://your-llm-api-endpoint"

# AI 分析并生成配置
sqlseed ai-suggest app.db --table bank_cards --output bank_cards.yaml

# 带自纠正的 AI 建议（默认 3 轮修正）
sqlseed ai-suggest app.db --table bank_cards --output bank_cards.yaml --verify

# 指定模型（默认自动选择最受欢迎的免费模型）
sqlseed ai-suggest app.db --table bank_cards --output bank_cards.yaml --model nvidia/nemotron-3-super-120b-a12b:free

# 跳过缓存
sqlseed ai-suggest app.db --table bank_cards --output bank_cards.yaml --no-cache
```

**AI 工作流程**：

```
1. 提取 Schema 上下文（列信息、索引、样本数据、外键、数据分布）
2. 构建带 Few-shot 示例的 LLM Prompt
3. LLM 返回 JSON 格式的列配置建议
4. AiConfigRefiner 自动验证配置的正确性
5. 若发现错误（未知生成器、类型不匹配等），自动向 LLM 发送修正请求
6. 最多 3 轮自纠正，输出经过验证的 YAML 配置
```

> **💡 环境变量**：支持 `SQLSEED_AI_API_KEY`、`SQLSEED_AI_BASE_URL`、`SQLSEED_AI_MODEL`。也支持 `OPENAI_API_KEY` / `OPENAI_BASE_URL` 作为回退。默认自动选择 OpenRouter 最受欢迎的免费模型（base_url `https://openrouter.ai/api/v1`），只需设置 API Key 即可零成本使用。如需指定模型，可通过 `--model` 参数或 `SQLSEED_AI_MODEL` 环境变量设置。

***

### 教程 9：MCP 服务器集成

通过 [Model Context Protocol](https://modelcontextprotocol.io/) 让 AI 助手（Claude、Cursor 等）直接操作 sqlseed：

```bash
# 安装 MCP 服务器
pip install mcp-server-sqlseed

# 启动
python -m mcp_server_sqlseed
```

**MCP 提供的能力**：

| 类型          | 名称                                        | 说明                                   |
| :---------- | :---------------------------------------- | :----------------------------------- |
| 📖 Resource | `sqlseed://schema/{db_path}/{table_name}` | 获取表 Schema 的 JSON 表示                 |
| 🔍 Tool     | `sqlseed_inspect_schema`                  | 检查 Schema（列、外键、索引、样本数据、schema\_hash） |
| 🤖 Tool     | `sqlseed_generate_yaml`                   | AI 驱动的 YAML 配置生成（含自纠正）。支持 `api_key`/`base_url`/`model` 参数覆盖环境变量 |
| ⚡ Tool      | `sqlseed_execute_fill`                    | 执行数据生成（支持 YAML 配置字符串，含 `enrich` 选项）  |

这意味着你可以在 AI 助手中说：

> "分析 `app.db` 中 `bank_cards` 表的结构，生成 YAML 配置，然后填充 5000 行数据。"

AI 助手会依次调用 `sqlseed_inspect_schema` → `sqlseed_generate_yaml` → `sqlseed_execute_fill`，无需你手动编写任何代码。

***

### 教程 10：自定义 Provider 插件

你可以创建自己的数据生成 Provider：

```python
# my_provider.py
from __future__ import annotations
from typing import Any

from sqlseed.generators import UnknownGeneratorError

class MyCustomProvider:
    """实现 DataProvider Protocol 即可。不需要继承任何基类。"""

    def __init__(self) -> None:
        self._locale: str = "en_US"

    @property
    def name(self) -> str:
        return "my_custom"

    def set_locale(self, locale: str) -> None:
        self._locale = locale

    def set_seed(self, seed: int) -> None:
        ...

    def generate(self, type_name: str, **params: Any) -> Any:
        if type_name == "string":
            return "custom_string"
        if type_name == "email":
            return "user@example.com"
        raise UnknownGeneratorError(type_name)

    # ... 按需处理你要支持的 generator 名称
    # 完整 Protocol 参见：src/sqlseed/generators/_protocol.py
```

如果你想复用内置的 generator name 分发逻辑，而不是手写 `generate()` 的路由，也可以直接继承 `BaseProvider` 后覆盖局部行为。

**注册方式 1：通过** **`pyproject.toml`** **entry-point（推荐）**

```toml
[project.entry-points."sqlseed"]
my_custom = "my_provider:MyCustomProvider"
```

**注册方式 2：通过插件 Hook**

```python
from sqlseed.plugins.hookspecs import hookimpl

class MyPlugin:
    @hookimpl
    def sqlseed_register_providers(self, registry):
        from my_provider import MyCustomProvider
        registry.register(MyCustomProvider())
```

***

## 🖥️ CLI 命令速查

```bash
# ═══════════════════════════════════════
# 📋 数据生成
# ═══════════════════════════════════════

# 填充数据（--count 在非 --config 模式下必填）
sqlseed fill app.db --table users --count 10000

# 完整参数
sqlseed fill app.db -t users -n 100000 \
    --provider mimesis \
    --locale zh_CN \
    --seed 42 \
    --batch-size 10000 \
    --clear \
    --enrich \
    --snapshot

# YAML 配置驱动（count 来自配置文件）
sqlseed fill --config generate.yaml

# Transform 脚本
sqlseed fill app.db -t users -n 10000 --transform transform.py

# 开启 debug 日志
SQLSEED_LOG_LEVEL=DEBUG sqlseed fill app.db -t users -n 10

# ═══════════════════════════════════════
# 🔍 查看与预览
# ═══════════════════════════════════════

# 预览数据（不写入）
sqlseed preview app.db --table users --count 5

# 查看所有表
sqlseed inspect app.db

# 查看列映射策略
sqlseed inspect app.db --table users --show-mapping

# ═══════════════════════════════════════
# 📸 快照与回放
# ═══════════════════════════════════════

# 生成配置模板
sqlseed init generate.yaml --db app.db

# 回放快照
sqlseed replay snapshots/2026-04-15_users.yaml

# ═══════════════════════════════════════
# 🤖 AI 功能
# ═══════════════════════════════════════

# AI 建议（需安装 sqlseed-ai）
sqlseed ai-suggest app.db -t users -o users.yaml
sqlseed ai-suggest app.db -t users -o users.yaml --verify

# 指定 API 配置
sqlseed ai-suggest app.db -t users -o users.yaml --api-key sk-xxx --base-url https://api.openai.com/v1

# 控制自纠正
sqlseed ai-suggest app.db -t users -o users.yaml --max-retries 0   # 禁用自纠正
sqlseed ai-suggest app.db -t users -o users.yaml --no-verify       # 跳过验证

# 跳过缓存
sqlseed ai-suggest app.db -t users -o users.yaml --no-cache
```

***

## 🧠 9 级智能列映射

sqlseed 的核心亮点之一是 `ColumnMapper` 的 9 级策略链。每一列都会按以下优先级尝试匹配：

```
Level 1 │ 自增主键          PK + AUTOINCREMENT / INTEGER → skip
        ▼
Level 2 │ 用户配置          columns={"email": "email"} 最高优先级
        ▼
Level 3 │ 自定义精确匹配    通过插件 Hook 注册的规则
        ▼
Level 4 │ 内置精确匹配      67 条规则：email→email, phone→phone, age→integer...
        ▼
Level 5 │ DEFAULT 检查      有默认值 → skip / __enrich__（enrich=True 时生成数据）
        ▼
Level 6 │ 自定义模式匹配    通过插件 Hook 注册的正则规则
        ▼
Level 7 │ 内置模式匹配      25 条正则：*_at→datetime, *_id→foreign_key, is_*→boolean...
        ▼
Level 8 │ NULLABLE 回退     可 NULL → skip / __enrich__
        ▼
Level 9 │ 类型忠实回退      VARCHAR(32)→最长32字符, INT8→0~255, BLOB(1024)→1024字节
```

这意味着：

- 列名 `user_email` → Level 7 模式匹配 `*_email` → `email` 生成器 ✅
- 列名 `is_verified` → Level 7 模式匹配 `is_*` → `boolean` 生成器 ✅
- 列类型 `VARCHAR(20)` → Level 9 类型回退 → 最长 20 字符的字符串 ✅
- 列有 `DEFAULT 1` → Level 5 → 跳过生成 ✅
- 列名 `gender` 有 `DEFAULT 'male'` → Level 4 精确匹配 → `choice` 生成器（精确匹配优先于 DEFAULT）✅

***

## 🧩 插件系统

sqlseed 通过 [pluggy](https://pluggy.readthedocs.io/) 提供 11 个 Hook 点，覆盖数据生成全生命周期：

| Hook                              | firstresult | 触发时机                   |
| :-------------------------------- | :---------: | :--------------------- |
| `sqlseed_register_providers`      |    <br />   | 注册自定义数据 Provider       |
| `sqlseed_register_column_mappers` |    <br />   | 注册自定义列映射规则             |
| `sqlseed_ai_analyze_table`        |      ✓      | AI 分析表 Schema（返回列配置建议） |
| `sqlseed_pre_generate_templates`  |      ✓      | AI 预计算候选值池             |
| `sqlseed_before_generate`         |    <br />   | 数据生成循环前                |
| `sqlseed_after_generate`          |    <br />   | 数据生成完成后                |
| `sqlseed_transform_row`           |    <br />   | 逐行变换（热路径，注意性能）         |
| `sqlseed_transform_batch`         |    <br />   | 逐批变换（支持链式处理）           |
| `sqlseed_before_insert`           |    <br />   | 每批写入 DB 前              |
| `sqlseed_after_insert`            |    <br />   | 每批写入 DB 后              |
| `sqlseed_shared_pool_loaded`      |    <br />   | SharedPool 注册后（值池已可读）     |

***

## 🏗️ 项目架构

```
src/sqlseed/
├── __init__.py              # 公共 API (fill, connect, fill_from_config, preview)
├── core/                    # ===== 核心编排层 =====
│   ├── orchestrator.py      # DataOrchestrator 主引擎
│   ├── mapper.py            # ColumnMapper 9 级策略链
│   ├── schema.py            # SchemaInferrer — 推断列、索引、数据分布
│   ├── relation.py          # RelationResolver + SharedPool — FK 与跨表共享
│   ├── column_dag.py        # ColumnDAG — 列依赖图 + 拓扑排序
│   ├── expression.py        # ExpressionEngine — 安全表达式 (simpleeval + 超时)
│   ├── constraints.py       # ConstraintSolver — 唯一性回溯求解
│   ├── transform.py         # TransformLoader — 用户脚本动态加载
│   └── result.py            # GenerationResult 数据类
├── generators/              # ===== 数据生成层 =====
│   ├── _protocol.py         # DataProvider Protocol + UnknownGeneratorError
│   ├── registry.py          # ProviderRegistry (entry-point 自动发现)
│   ├── base_provider.py     # 内置基础生成器（零依赖）
│   ├── faker_provider.py    # Faker 适配器
│   ├── mimesis_provider.py  # Mimesis 适配器
│   └── stream.py            # DataStream 流式生成 + 约束回溯 + choice/foreign_key 特判
├── database/                # ===== 数据库层 =====
│   ├── _protocol.py         # DatabaseAdapter Protocol (ColumnInfo, ForeignKeyInfo, IndexInfo)
│   ├── sqlite_utils_adapter.py   # 默认适配器
│   ├── raw_sqlite_adapter.py     # sqlite3 回退适配器
│   └── optimizer.py         # PragmaOptimizer 三级优化
├── plugins/                 # ===== 插件层 =====
│   ├── hookspecs.py         # 11 个 pluggy Hook 定义
│   └── manager.py           # PluginManager
├── config/                  # ===== 配置管理 =====
│   ├── models.py            # Pydantic 模型 (GeneratorConfig/TableConfig/ColumnConfig)
│   ├── loader.py            # YAML/JSON 加载与保存
│   └── snapshot.py          # 快照保存与回放
├── cli/                     # ===== CLI =====
│   └── main.py              # click 命令 (fill/preview/inspect/init/replay/ai-suggest)
└── _utils/                  # ===== 内部工具 =====
    ├── sql_safe.py          # quote_identifier — SQL 注入防护
    ├── schema_helpers.py    # AUTOINCREMENT 检测
    ├── metrics.py           # MetricsCollector 性能度量
    ├── progress.py          # Rich 进度条
    └── logger.py            # structlog 日志

plugins/
├── sqlseed-ai/              # AI 插件 — LLM 驱动的智能配置
│   └── src/sqlseed_ai/      # SchemaAnalyzer, AiConfigRefiner, Few-shot 示例...
└── mcp-server-sqlseed/      # MCP 服务器 — AI 助手交互
    └── src/mcp_server_sqlseed/   # FastMCP 工具 (sqlseed_inspect_schema/sqlseed_generate_yaml/sqlseed_execute_fill)
```

***

## 🛠️ 开发

```bash
# 运行测试（含覆盖率）
pytest

# 代码检查
ruff check src/ tests/

# 自动修复
ruff check --fix src/ tests/

# 类型检查
mypy src/sqlseed/
```

测试覆盖了所有核心模块，路径结构与 `src/` 一一对应：`test_core/`、`test_database/`、`test_generators/`、`test_plugins/`、`test_config/`、`test_utils/`。

***

## 📄 License

[AGPL-3.0-or-later](LICENSE)

***

<div align="center">

**🌱 sqlseed** — *Stop writing fixtures. Start generating data.*

</div>
