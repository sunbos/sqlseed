<div align="center">

# 🌱 sqlseed

[English](https://github.com/sunbos/sqlseed/blob/main/README.md) | **[中文](https://github.com/sunbos/sqlseed/blob/main/README.zh-CN.md)**

### 声明式多数据库测试数据生成工具包

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

# 数据库和 users 表需要已经存在。
result = sqlseed.fill("test.db", table="users", count=100_000)
print(result.count, result.errors)  # 检查实际写入数和失败原因。
```

***

## 💡 为什么选择 sqlseed？

| 特性 | sqlseed | 手写脚本 | SQL Fixtures |
| :--- | :-----: | :----: | :----------: |
| 零配置智能生成 |    ✅    |    ❌   |       ❌      |
| 外键自动维护 |    ✅    |   手动   |      手动      |
| 分批生成大量数据 | ✅ 内置支持 | 需自行实现 | 需生成对应脚本 |
| 列语义推断 | ✅ 9 级策略 |    ❌   |       ❌      |
| 可重复生成 |  ✅ seed  |  ⚠️ 手动 |       ✅      |
| AI 智能调优 |  ✅ LLM  |    ❌   |       ❌      |
| 配置热重用 |  ✅ YAML  |    ❌   |       ❌      |

## ✨ 核心特性

<table>
<tr>
<td width="50%">

**🚀 零配置智能生成**

自动推断数据库 Schema，通过 9 级策略链为每列选择生成器。列名是 `email`？生成邮箱。列名是 `*_at`？生成时间戳。特定业务关系与复杂约束可能需要显式规则。

</td>
<td width="50%">

**🎯 声明式精确控制**

通过 Python API 或 YAML/JSON 配置精确控制每一列的数据生成策略、约束条件和空值比率。

</td>
</tr>
<tr>
<td>

**🔗 外键自动排序**

拓扑排序检测表依赖，SharedPool 复用真实父键值。支持范围内的外键会协调生成；不支持的复合或 schema-qualified 关系在生成前明确拒绝，详见下方支持约定。

</td>
<td>

**🌊 分批流式生成**

`DataStream` 通过 `Iterator[list[dict]]` 逐批 yield，并遵守配置的批大小上限。UNIQUE 跟踪、父键池和自引用处理仍有额外内存成本，不能保证所有结构的总内存占用恒定。

</td>
</tr>
<tr>
<td>

**🧮 表达式引擎 & 约束求解**

支持派生列计算（`short_code = project_no[-8:]`），唯一性约束回溯求解，超时保护防止死循环。

</td>
<td>

**🤖 AI 一等公民**

`sqlseed-ai` 插件通过 LLM 分析 Schema 语义，自动生成 YAML 配置建议，支持自纠正闭环。

</td>
</tr>
<tr>
<td>

**🧩 12 个 Hook 全生命周期**

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

本 README 描述 sqlseed 0.2.4 的五包工作台，版本详情见[发布记录](https://github.com/sunbos/sqlseed/releases)。Core、AI、MCP 的 0.2.3 使用旧布局，其[对应版本文档](https://github.com/sunbos/sqlseed/tree/v0.2.3)不包含独立的 CLI 和 Web 包。

### 从 PyPI 安装

使用 Python 3.10+ 和新的虚拟环境，按需安装所需入口：

```bash
python -m venv .venv
# macOS/Linux：source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1

# 离线 Python API
python -m pip install 'sqlseed==0.2.4'

# 按需添加入口，各包会拉取兼容依赖
python -m pip install 'sqlseed-cli==0.2.4'
python -m pip install 'sqlseed-ai[mcp]==0.2.4'
python -m pip install 'mcp-server-sqlseed==0.2.4'
python -m pip install 'sqlseed-web==0.2.4'
python -m pip check
```

Core 不提供命令行入口，`sqlseed` 命令由 `sqlseed-cli` 提供。替换 0.2.3 环境前请阅读[升级说明](https://sunbos.github.io/sqlseed/migration.zh-CN/)。

Faker 和 SQLAlchemy 是 Core 的必需依赖；SQLite 无需额外驱动。需要 PostgreSQL 或 Mimesis 时，将 Core 安装项替换为 `'sqlseed[postgres,mimesis]==0.2.4'`。`all` extra 包含 Core 的可选工具与 CLI；AI、MCP 和 Web 仍是独立包。

### 从源码安装（开发与候选版本）

在源码目录的新虚拟环境中，在同一次依赖解析中提供本地 Core 与插件：

```bash
git clone https://github.com/sunbos/sqlseed.git
cd sqlseed
python -m venv .venv
# macOS/Linux：source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
python -m pip install -e . -e ./plugins/sqlseed-cli -e './plugins/sqlseed-ai[mcp]' -e ./plugins/mcp-server-sqlseed -e ./plugins/sqlseed-web
python -m pip check
sqlseed --help
```

只需要离线 Python API 时安装 `-e .`；只需要 Core 和 Web 时安装 `-e . -e ./plugins/sqlseed-web`。需要 PostgreSQL 或 Mimesis 时，将 `-e .` 替换为 `-e '.[postgres,mimesis]'`。候选 wheel 必须从同一次 CI 构建成套安装。

### 本地 Web 工作台

安装 Core 和 Web 后，运行 `sqlseed-web` 并打开 `http://127.0.0.1:8630`。工作台支持 schema 关系图、字段规则编辑、版本化配置、依赖检查、预览、多表生成与持久运行记录，无需 AI 即可使用。详见 [Web 工作台指南](https://sunbos.github.io/sqlseed/web-workbench/)。

设置页可从包索引安装或卸载可选组件，前提是兼容版本已发布。界面包变更需要 macOS/Linux 的可写独立 virtualenv 及默认启动器；有工作正在执行时会阻止操作，已有版本受到保护，Core、Web、Faker、Base 不开放移除。尚未发布的候选插件请按上述源码方式安装。恢复行为和连接限制见 [Web 指南](https://sunbos.github.io/sqlseed/web-workbench/)。

### 开发与文档构建

激活虚拟环境后，从仓库根目录运行：

```bash
python -m pip install -e '.[dev,all,docs]' -e ./plugins/sqlseed-cli -e './plugins/sqlseed-ai[dev,mcp]' -e ./plugins/mcp-server-sqlseed -e './plugins/sqlseed-web[dev]'
pytest
ruff check src/ tests/ plugins/
ruff format --check src/ tests/ plugins/
mypy src/sqlseed/ plugins/
lint-imports
python scripts/sync_docs.py --check
python -m mkdocs build --strict
```

发布准备与正式 PyPI 安装验收见[发布指南](https://sunbos.github.io/sqlseed/releasing/)。

***

## 🚀 快速开始

完整体验推荐 [可复现订单流程](https://github.com/sunbos/sqlseed/blob/main/examples/order_workflow/README.md)：包含用户、商品、订单与明细的真实生成、坏规则诊断、修正与离线重放。[支持与维护约定](https://sunbos.github.io/sqlseed/maintainable-release/)说明当前能力边界；[项目展示说明](https://sunbos.github.io/sqlseed/project-showcase/)提供演示顺序和架构讲解。

### 使用示例数据库体验

想立即体验 sqlseed？构建示例数据库：

```bash
python examples/build_demo_db.py
```

然后探索：

```bash
# members.org_code 引用 organizations.org_code，先生成父表数据。
sqlseed fill examples/sqlseed_demo.db --table organizations --count 10
sqlseed preview examples/sqlseed_demo.db --table members --count 5
sqlseed inspect examples/sqlseed_demo.db --show-mapping
sqlseed fill examples/sqlseed_demo.db --table members --count 100
```

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
print(result.count, result.errors)
# 10000 []
```

sqlseed 会自动：

- ✅ 跳过 `id`（自增主键）
- ✅ 跳过 `is_active`（有默认值）
- ✅ `name` → 生成真实姓名
- ✅ `email` → 生成邮箱地址
- ✅ `age` → 生成整数；需要符合年龄含义的范围时，请显式配置
- ✅ `phone` → 生成电话号码
- ✅ `created_at` → 生成日期时间（匹配 `*_at` 模式）
- ✅ `balance` → 生成浮点数

**这个简单结构可以使用推断默认值；生成复杂数据前，请检查并配置特定业务规则。**

### 连接 PostgreSQL

sqlseed 除 SQLite 外还支持 PostgreSQL。传入 SQLAlchemy URL 替代文件路径即可：

```python
import sqlseed

# PostgreSQL（需安装：pip install "sqlseed[postgres]"）
result = sqlseed.fill(
    "postgresql+psycopg://user:password@localhost:5432/mydb",
    table="users",
    count=10_000,
)
print(result)
```

两种数据库使用相同的 public API，但方言行为与约束支持范围不同。当前生成会拒绝 PostgreSQL 复合外键及反射出的 schema-qualified 引用；SQLite 完整元组协调覆盖两列外键。详见 [支持与验证范围](https://sunbos.github.io/sqlseed/maintainable-release/)，其中区分本地 SQLite 验证与真实 PostgreSQL 集成测试。

***

## 📖 使用教程

### 教程 1：Python API — 精确控制每一列

```python
import sqlseed

result = sqlseed.fill(
    "app.db",
    table="users",
    count=50_000,
    columns={
        "email": "email",
        "phone": "phone",
        "age": {"type": "integer", "min_value": 18, "max_value": 65},
        "balance": {"type": "float", "min_value": 0.0, "max_value": 100000.0, "precision": 2},
        "name": "name",
    },
    provider="mimesis",
    locale="zh_CN",
    seed=42,
    clear_before=True,
    enrich=True,
)
print(result.count, result.errors)
```

本例沿用前文的 `users` 表。要在已有列中生成枚举值，可以使用
`{"type": "choice", "choices": ["active", "inactive", "banned"]}`。
Transform 脚本在教程 5 中介绍，使用前需要创建脚本及其目标列。

#### 支持的生成器类型

| 生成器 | 说明 | 参数示例 |
| :----- | :--- | :------- |
| `string` | 随机字符串 | `min_length`, `max_length`, `charset` |
| `integer` | 整数 | `min_value`, `max_value` |
| `float` | 浮点数 | `min_value`, `max_value`, `precision` |
| `boolean` | 布尔值 | — |
| `name` | 人名 | — |
| `first_name` | 名 | — |
| `last_name` | 姓 | — |
| `email` | 邮箱 | — |
| `phone` | 电话 | — |
| `address` | 地址 | — |
| `company` | 公司名 | — |
| `url` | URL | — |
| `ipv4` | IPv4 地址 | — |
| `uuid` | UUID | — |
| `date` | 日期 | `start_year`, `end_year` |
| `datetime` | 日期时间 | `start_year`, `end_year` |
| `time` | 一天中的时间 | `all_day`, `start_time`, `end_time` |
| `timestamp` | Unix 时间戳 | — |
| `text` | 长文本 | `min_length`, `max_length` |
| `sentence` | 句子 | — |
| `word` | 真实英文单词 | — |
| `catch_phrase` | 商业口号（多词短语） | — |
| `password` | 密码 | `length` |
| `choice` | 从列表选择 | `choices` |
| `weighted_choice` | 加权随机选择 | `choices`（`{value, weight}` 列表）或 `weighted_choices`（字典） |
| `json` | JSON 字符串 | `schema` |
| `pattern` | 正则匹配 | `regex` |
| `template` | 模板字符串（带占位符） | `template`, `sequence_start`, `sequence_step` |
| `bytes` | 二进制数据 | `length` |
| `username` | 用户名 | — |
| `city` | 城市 | — |
| `country` | 国家 | — |
| `state` | 省/州 | — |
| `zip_code` | 邮政编码 | — |
| `job_title` | 职位名称 | — |
| `country_code` | 国家代码 | — |
| `foreign_key` | 外键引用 | `ref_table`, `ref_column`, `strategy` |
| `skip` | 跳过（使用默认值/NULL） | — |

Provider dispatch 支持 36 个生成器名称；`foreign_key` 和 `skip` 由编排层处理。

***

### 教程 2：多表关联 — 自动维持外键完整性

先在前文的 `app.db` 中创建引用 `users` 的子表：

```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount REAL,
    quantity INTEGER,
    status TEXT,
    created_at TEXT
);
```

```python
import sqlseed

with sqlseed.connect("app.db", provider="mimesis", locale="zh_CN") as db:
    # 步骤 1：先填充父表
    users_result = db.fill("users", count=10_000, seed=42)
    print(users_result.count, users_result.errors)

    # 步骤 2：填充子表 — sqlseed 自动检测外键约束，
    #         从 users.id 中随机选取值填入 orders.user_id
    orders_result = db.fill("orders", count=50_000, columns={
        "amount": {"type": "float", "min_value": 9.99, "max_value": 999.99, "precision": 2},
        "quantity": {"type": "integer", "min_value": 1, "max_value": 20},
        "status": {"type": "choice", "choices": ["pending", "paid", "shipped", "delivered"]},
    })
    print(orders_result.count, orders_result.errors)

    print(db.report())
```

`db.report()` 显示数据库当前总行数，包含之前运行写入的数据。
没有声明 FK 的关系请使用显式 `associations`；仅有 `member_no` 这样的同名列不会建立关联。

#### 显式跨表关联（ColumnAssociation）

执行配置前，先在 `app.db` 中创建这两张表：

```sql
CREATE TABLE departments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
CREATE TABLE employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL,
    name TEXT NOT NULL
);
```

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
    target_tables:
      - employees
    strategy: shared_pool
```

***

### 教程 3：YAML 配置文件驱动批量生成

本例向前文已经创建的 `users` 和 `orders` 表追加数据。

```bash
# 生成配置模板
sqlseed init generate.yaml --db app.db

# 编辑后执行
sqlseed fill --config generate.yaml
```

```yaml
# generate.yaml
db_path: "app.db"
provider: mimesis
locale: zh_CN
optimize_pragma: true

tables:
  - name: users
    count: 100000
    seed: 42
    columns:
      - name: name
        generator: name
      - name: email
        generator: email
        null_ratio: 0.05       # 此可空列有 5% 概率为 NULL
      - name: phone
        generator: phone
      - name: age
        generator: integer
        params:
          min_value: 18
          max_value: 65

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

***

### 教程 4：派生列与表达式引擎

先在 `app.db` 中创建目标表：

```sql
CREATE TABLE projects (
    project_no TEXT NOT NULL UNIQUE,
    short_code TEXT NOT NULL UNIQUE,
    region_code TEXT NOT NULL,
    member_no TEXT NOT NULL UNIQUE
);
```

```yaml
db_path: "app.db"
provider: mimesis
tables:
  - name: projects
    count: 10000
    seed: 42
    columns:
      - name: project_no
        generator: pattern
        params:
          regex: "PRJ-\\d{6}"       # 项目编号模式
        constraints:
          unique: true

      - name: short_code
        derive_from: project_no       # 依赖 project_no
        expression: "value[-6:]"   # 取后 6 位
        constraints:
          unique: true

      - name: region_code
        derive_from: project_no
        expression: "value[-4:]"   # 取后 4 位

      - name: member_no
        generator: pattern
        params:
          regex: "M-\\d{4}"         # 成员编号模式
        constraints:
          unique: true
```

**运作原理**：

1. sqlseed 构建列依赖 DAG：`project_no → short_code, region_code`
2. 拓扑排序确定生成顺序
3. 先生成 `project_no`，再通过表达式 `value[-6:]` 计算 `short_code`
4. 如果 `short_code` 的唯一性约束失败，回溯重新生成 `project_no`

#### 表达式引擎支持的函数（26 个）

| 函数 | 用法 | 说明 |
| :--- | :--- | :--- |
| `len(s)` | `len(value)` | 获取长度 |
| `int(s)` | `int(value)` | 转整数 |
| `str(s)` | `str(value)` | 转字符串 |
| `float(s)` | `float(value)` | 转浮点数 |
| `hex(n)` | `hex(value)` | 转十六进制 |
| `oct(n)` | `oct(value)` | 转八进制 |
| `bin(n)` | `bin(value)` | 转二进制 |
| `abs(n)` | `abs(value)` | 绝对值 |
| `min(*args)` | `min(a, b)` | 最小值 |
| `max(*args)` | `max(a, b)` | 最大值 |
| `round(n, ndigits)` | `round(value, 2)` | 四舍五入到 N 位 |
| `upper(s)` | `upper(value)` | 转大写 |
| `lower(s)` | `lower(value)` | 转小写 |
| `strip(s)` | `strip(value)` | 去两端空白 |
| `lstrip(s)` | `lstrip(value)` | 去左端空白 |
| `rstrip(s)` | `rstrip(value)` | 去右端空白 |
| `zfill(s, width)` | `zfill(value, 10)` | 零填充 |
| `replace(s, old, new)` | `replace(value, "-", "")` | 替换 |
| `substr(s, start, end)` | `substr(value, 0, 8)` | 子串 |
| `lpad(s, width, char)` | `lpad(value, 8, "0")` | 左填充 |
| `rpad(s, width, char)` | `rpad(value, 8, "0")` | 右填充 |
| `concat(*args)` | `concat("PRE_", value)` | 拼接 |
| `random_float(min, max)` | `random_float(0, value)` | 范围内随机浮点数 |
| `random_int(min, max)` | `random_int(1, 100)` | 范围内随机整数 |
| `random_choice(seq)` | `random_choice([1,2,3])` | 从序列中随机选择 |
| `timedelta(days, seconds)` | `value + timedelta(days=7)` | 日期/时间算术 (给日期源列增加间隔) |
| 切片 | `value[-8:]` | Python 切片语法 |
| 数学 | `value * 2 + 1` | 基本数学运算 |

> ⚠️ **安全保护**：表达式引擎基于 `simpleeval`，具有 5 秒超时保护，不允许 `import`、`exec` 或文件 I/O 操作。

***

### 教程 5：Transform 脚本 — 复杂业务逻辑

先给已有的 `users` 表添加脚本要写入的列：

```sql
ALTER TABLE users ADD COLUMN vip_level INTEGER;
```

```python
# transform_users.py
def transform_row(row, ctx):
    """每一行生成后都会经过此函数处理。"""
    age = row.get("age", 0)
    if age >= 60:
        row["vip_level"] = 3
    elif age >= 40:
        row["vip_level"] = 2
    else:
        row["vip_level"] = 1
    return row
```

```bash
# CLI 使用
sqlseed fill app.db --table users --count 10000 --transform transform_users.py
```

***

### 教程 6：预览与调试

```python
rows = sqlseed.preview("app.db", table="users", count=5, seed=42)
for row in rows:
    print(row)
```

```bash
# CLI 预览（Rich 表格输出）
sqlseed preview app.db --table users --count 5

# 查看列映射策略
sqlseed inspect app.db --table users --show-mapping
```

***

### 教程 7：快照与回放

快照保存生成配置和 seed，不是数据库备份。回放沿用保存的 `clear_before`；
下面的例子会追加一批数据。生成的 ID 和其他值可能受已有数据、schema、provider
及包版本影响。

```bash
# 生成并保存快照
sqlseed fill app.db --table users --count 10000 --seed 42 --snapshot
# → Snapshot saved: <cache_dir>/snapshots/YYYY-MM-DD_HHMMSS_ffffff_users.yaml

# 将路径替换为上方命令实际输出的快照路径。
sqlseed replay "/path/to/saved-snapshot.yaml"
```

***

### 教程 8：AI 智能配置（sqlseed-ai 插件）

sqlseed-ai 插件提供 **3 个 CLI 命令**：

| 命令 | 用途 | 适用场景 |
| :--- | :--- | :--- |
| `ai-suggest` | 单表 LLM 分析 + 自纠正 | 单表分析，支持 `--verify` 校验 |
| `ai-analyze` | 全库/部分表分析，走 v4 AutoHealOrchestrator（默认路径） | 多表 YAML 生成，含契约驱动自愈 |
| `auto-heal` | 通过 LLM + 规则管道修复损坏的 YAML 配置 | 修复 `sqlseed fill` 失败的 YAML 文件 |

```bash
pip install sqlseed-ai
export SQLSEED_AI_API_KEY="your-api-key"
export SQLSEED_AI_BACKEND=google_ai_studio

# ─────────────────────────────────────────────
# ai-suggest: 单表 LLM 分析
# ─────────────────────────────────────────────

# AI 分析并生成配置
sqlseed ai-suggest app.db --table projects --output projects.yaml

# 带自纠正的 AI 建议（默认 3 轮修正）
sqlseed ai-suggest app.db --table projects --output projects.yaml --verify

# 指定模型（后端通过 SQLSEED_AI_BACKEND 环境变量选择，无 --backend 选项）
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-26b-a4b-it
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-31b-it
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table projects -o projects.yaml --model google/gemma-4-e4b
SQLSEED_AI_BACKEND=ollama sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma4:e4b

# ─────────────────────────────────────────────
# ai-analyze: 全库分析（v4 架构默认路径）
# ─────────────────────────────────────────────

# 分析整个数据库并生成 YAML（v4 AutoHealOrchestrator）
sqlseed ai-analyze --db app.db -o config.yaml

# 输出到 stdout（不指定 -o）
sqlseed ai-analyze --db app.db

# 通过 --url 连接多数据库
sqlseed ai-analyze --url "postgresql+psycopg://user:pass@host/db" -o config.yaml

# 记录完整 LLM 交互用于调试
sqlseed ai-analyze --db app.db -o config.yaml --log-llm

# ─────────────────────────────────────────────
# auto-heal: 修复损坏的 YAML 配置
# ─────────────────────────────────────────────

# ai-analyze 之后若 `sqlseed fill` 失败，可修复 YAML
sqlseed auto-heal --db app.db --config broken.yaml -o healed.yaml

# 使用不同的 LLM 模型进行修复
sqlseed auto-heal --db app.db --config broken.yaml -o healed.yaml --model gemma-4-26b-a4b-it
```

**Gemma 4 原生函数调用（GEMMA_TOOLS）**：

sqlseed-ai 支持 Gemma 4 后端，调用协议由 `SQLSEED_AI_TOOL_CALLING_PROTOCOL`
控制，不仅由模型名称决定。可配置的后端如下：

| 后端 | 说明 | 配置方式 |
| :--- | :--- | :--- |
| **Google AI Studio** | 官方 API，推荐 Gemma 4 26B/31B | `SQLSEED_AI_BACKEND=google_ai_studio` |
| **LM Studio** | 本地推理，适合 Gemma 4 2B/4B | `SQLSEED_AI_BACKEND=lm_studio`（默认 URL `http://127.0.0.1:1234/v1`） |
| **Ollama** | 本地推理，适合 Gemma 4 2B/4B/26B | `SQLSEED_AI_BACKEND=ollama` |
| **OpenAI-compatible** | 通用 OpenAI 兼容端点（如 OpenRouter、DeepSeek） | `SQLSEED_AI_BACKEND=openai_compat` |

| 请求的协议 | Google AI Studio | OpenAI-compatible | LM Studio / Ollama |
| :--------- | :--------------- | :---------------- | :----------------- |
| `gemma4`（默认） | Gemma 4 原生调用 | 回退 JSON/text | 回退 JSON/text |
| `openai` | OpenAI tools API | OpenAI tools API | 回退 JSON/text |
| `none` | JSON/text | JSON/text | JSON/text |

未显式选择 backend 且没有可识别的 URL 时，配置使用 `openai_compat`，必须提供
base URL，并选择该端点支持的模型。模型和后端也需要支持所请求的 tools API。

> **💡 OpenRouter（免费方案）**：没有付费 API Key 的用户，可以使用 OpenRouter 的免费模型。设置 `SQLSEED_AI_BACKEND=openai_compat`、`SQLSEED_AI_BASE_URL=https://openrouter.ai/api/v1`、`SQLSEED_AI_MODEL=<免费模型名>`。

> **💡 环境变量**：支持 `SQLSEED_AI_API_KEY`、`SQLSEED_AI_BASE_URL`、`SQLSEED_AI_MODEL`、`SQLSEED_AI_BACKEND`。也支持 `OPENAI_API_KEY` / `OPENAI_BASE_URL` 作为回退。

***

### 教程 9：MCP 服务器集成

```bash
# 安装核心 MCP 服务器（无 LLM 依赖）
pip install mcp-server-sqlseed

# 安装 AI MCP 服务器（LLM 驱动，依赖 sqlseed-ai）
pip install "sqlseed-ai[mcp]"

# 配置 Claude Desktop
```

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    }
  }
}
```

**MCP 提供的能力**：

**mcp-server-sqlseed**（2 个工具，0 个资源 —— 核心，无 LLM 依赖）：

| 类型 | 名称 | 说明 |
| :--- | :--- | :--- |
| 🤖 Tool | `sqlseed_generate_yaml` | 规则驱动的 YAML 配置生成（经由 `ColumnMapper`） |
| ⚡ Tool | `sqlseed_execute_fill` | 执行数据生成（支持 YAML 配置字符串，含 `enrich` 选项） |

**sqlseed-ai[mcp]**（4 个工具，0 个资源 —— LLM 驱动，通过 `pip install "sqlseed-ai[mcp]"` 安装）：

| 类型 | 名称 | 说明 |
| :--- | :--- | :--- |
| 🧠 Tool | `sqlseed_ai_generate_yaml` | AI 驱动的 YAML 配置生成（含自纠正） |
| 🧠 Tool | `sqlseed_gemma4_analyze` | 使用 Gemma 4 和解析后的后端协议分析 Schema |
| 🧠 Tool | `sqlseed_gemma4_agent_fill` | Gemma 4 Agent 模式端到端数据生成（分析→配置→填充） |
| 🧠 Tool | `sqlseed_list_gemma_models` | 列出可用的 Gemma 4 模型及后端支持情况 |

***

### 教程 10：自定义 Provider 插件

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
```

**注册方式 1：通过 `pyproject.toml` entry-point（推荐）**

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

使用 `fill --config` 时，数据库目标仅由配置中的 `db_path` 或 `url` 提供；
同时传入位置参数数据库路径或 `--url` 会在写入前报错。任一配置表生成失败时，
命令会显示错误和已提交行数，并以非零状态退出。多表生成不构成一个原子事务。
未显式指定 `--provider`、`--locale`、`--batch-size` 时保留配置值；显式传入的值
会覆盖配置，即使该值恰好等于 CLI 默认值。

```bash
# ═══ 数据生成 ═══
sqlseed fill app.db --table users --count 10000
sqlseed fill app.db -t users -n 100000 --provider mimesis --locale zh_CN --seed 42 --batch-size 10000 --clear --enrich --snapshot
sqlseed fill --config generate.yaml
sqlseed fill app.db -t users -n 10000 --transform transform.py
SQLSEED_LOG_LEVEL=DEBUG sqlseed fill app.db -t users -n 10

# ═══ 查看与预览 ═══
sqlseed preview app.db --table users --count 5
sqlseed inspect app.db
sqlseed inspect app.db --table users --show-mapping

# ═══ 快照与回放 ═══
sqlseed init generate.yaml --db app.db
sqlseed replay "/path/to/saved-snapshot.yaml"  # 使用 --snapshot 实际输出的路径

# ═══ AI 功能 ═══
sqlseed ai-suggest app.db -t users -o users.yaml
sqlseed ai-suggest app.db -t users -o users.yaml --verify
SQLSEED_AI_BACKEND=openai_compat sqlseed ai-suggest app.db -t users -o users.yaml \
    --api-key your-api-key --base-url https://your-api-endpoint/v1 --model your-model
sqlseed ai-suggest app.db -t users -o users.yaml --max-retries 0
sqlseed ai-suggest app.db -t users -o users.yaml --no-cache

# ═══ AI 后端选择（通过环境变量，无 --backend 选项）═══
SQLSEED_AI_BACKEND=google_ai_studio sqlseed ai-suggest app.db -t users -o users.yaml --model gemma-4-26b-a4b-it
SQLSEED_AI_BACKEND=ollama sqlseed ai-suggest app.db -t users -o users.yaml --model gemma4:e4b
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db -t users -o users.yaml --model google/gemma-4-e4b
SQLSEED_AI_BACKEND=openai_compat sqlseed ai-suggest app.db -t users -o users.yaml --model your-model --base-url https://your-api-endpoint

# ═══ 全库分析与自愈（v4 默认路径）═══
sqlseed ai-analyze --db app.db -o config.yaml
sqlseed ai-analyze --url "postgresql+psycopg://user:pass@host/db" -o config.yaml

# ═══ 修复损坏的 YAML 配置 ═══
sqlseed auto-heal --db app.db --config broken.yaml -o healed.yaml
```

***

## 🧠 9 级智能列映射

```
Level 1 │ 自增主键          数据库显式自动分配 → skip
        ▼
Level 2 │ 用户配置          columns={"email": "email"} 最高优先级
        ▼
Level 3 │ 自定义精确匹配    通过插件 Hook 注册的规则
        ▼
Level 4 │ 内置精确匹配      <!-- BEGIN:AUTO-GENERATED:exact-match-rule-count -->75<!-- END:AUTO-GENERATED:exact-match-rule-count --> 条规则：email→email, phone→phone, age→integer...
        ▼
Level 5 │ DEFAULT 检查      有默认值 → skip / __enrich__（enrich=True 时生成数据）
        ▼
Level 6 │ 自定义模式匹配    通过插件 Hook 注册的正则规则
        ▼
Level 7 │ 内置模式匹配      <!-- BEGIN:AUTO-GENERATED:pattern-match-rule-count -->29<!-- END:AUTO-GENERATED:pattern-match-rule-count --> 条正则：*_at→datetime, *_id→foreign_key, is_*→boolean...
        ▼
Level 8 │ NULLABLE 回退     可 NULL → skip / __enrich__
        ▼
Level 9 │ 类型忠实回退      VARCHAR(32)→最长32字符, INT8→0~255, BLOB(1024)→1024字节
```

显式生成器参数优先于名称规则默认值。同一生成器继承默认参数；在 `string` 与 `text` 之间切换时，只继承共有的 `min_length`、`max_length`。`sentence` 不继承字符串或文本参数，`text` 不继承 `charset`；用户显式提供不支持的参数时仍会报告配置错误。

显式长度上下限会保留并交给校验，即使 `min_length` 大于 `max_length`。SQLite 主键仅在元数据确认是真实 rowid 别名时跳过默认生成。`WITHOUT ROWID` 和列内 `INTEGER PRIMARY KEY DESC` 按普通列处理；表级 `PRIMARY KEY(id DESC)` 仍可能是 rowid 别名。隐式 rowid 别名仍允许用户显式指定 generator。

`faker_method` 或 `mimesis_method` 配合 `native_params` 可独立配置 source 列，无须指定 `generator`；方法须对应当前 provider。UNIQUE 重试仍调用指定的 native 方法。未知方法或非法 native 参数明确失败，不会静默改为推断生成的数据。同时给出普通 generator 时，另一 provider 的 native 提示不影响该 generator 的正常回退。

部分 UNIQUE 索引保留 `is_partial` 元数据标记。WHERE 条件由数据库执行，不推导为无条件的单列或组合 UNIQUE。适用行发生重复时可能在写入批次时失败；默认逐批提交保留此前成功批次。SQLite 表名在反射、生成和依赖排序前按 ASCII 大小写不敏感规则解析为数据库名称；PostgreSQL 保持精确名称匹配。

单列字面量 CHECK 会对 `AND` 子句及多条 CHECK 声明取交集。严格数值边界先保留 SQL 含义，再按 integer/float generator 处理。用户的 `constraints.min_value`、`max_value`、`regex` 会检查生成的非 NULL 值；regex 要求匹配整个字符串，失败时在有限预算内重试或回溯。

Float 边界向生成器的小数精度网格内收，因此 precision 为 2 时，`0.005 < x < 0.015` 仍允许 `0.01`。若枚举没有精确交集，但 SQL affinity/collation 可能让字面量等价，则保留原候选交给数据库验证；此降级不保证每个候选都满足全部 CHECK。

追加生成通过候选键点查避开数据库已有的 UNIQUE/主键组合，不预加载全表。同一 seed 可能重放很长的已有键前缀并耗尽重试预算；这不代表唯一值空间已经用尽。

示例：

- 列名 `user_email` → Level 7 模式匹配 `*_email` → `email` 生成器 ✅
- 列名 `is_verified` → Level 7 模式匹配 `is_*` → `boolean` 生成器 ✅
- 列类型 `VARCHAR(20)` → Level 9 类型回退 → 最长 20 字符的字符串 ✅
- 列有 `DEFAULT 1` → Level 5 → 跳过生成 ✅
- 列名 `gender` 有 `DEFAULT 'male'` → Level 4 精确匹配 → `choice` 生成器（精确匹配优先于 DEFAULT）✅

***

## 🧩 插件系统

sqlseed 通过 [pluggy](https://pluggy.readthedocs.io/) 提供 12 个 Hook 点：

| Hook | firstresult | 触发时机 |
| :--- | :---------: | :------- |
| `sqlseed_register_providers` |    <br />   | 注册自定义数据 Provider |
| `sqlseed_register_column_mappers` |    <br />   | 注册自定义列映射规则 |
| `sqlseed_ai_analyze_table` |      ✓      | AI 分析表 Schema（返回列配置建议） |
| `sqlseed_apply_ai_suggestions` |      ✓      | 高层 AI 中介（orchestrator 入口；实现在 `sqlseed_ai.ai_mediator`） |
| `sqlseed_pre_generate_templates` |      ✓      | AI 预计算候选值池 |
| `sqlseed_before_generate` |    <br />   | 数据生成循环前 |
| `sqlseed_after_generate` |    <br />   | 数据生成完成后 |
| `sqlseed_transform_row` |    <br />   | 已声明 hookspec；普通 Core 生成流程不调用 |
| `sqlseed_transform_batch` |    <br />   | 逐批变换（各插件接收同一批输入，取最后一个非 `None` 结果） |
| `sqlseed_before_insert` |    <br />   | 每批写入 DB 前 |
| `sqlseed_after_insert` |    <br />   | 每批写入 DB 后 |
| `sqlseed_shared_pool_loaded` |    <br />   | SharedPool 注册后（值池已可读） |

***

## 🏗️ 项目架构

```
src/sqlseed/
├── __init__.py              # 公共 API (fill, connect, fill_from_config, preview, load_config)
├── core/                    # ===== 核心编排层 =====
│   ├── orchestrator/        # DataOrchestrator（4 个 mixin、共享状态及辅助模块）
│   │   ├── __init__.py
│   │   ├── _common.py
│   │   ├── _connection.py
│   │   ├── _specs.py
│   │   ├── _generation.py
│   │   ├── _self_ref.py
│   │   ├── _session.py
│   │   └── _query.py
│   ├── mapper.py            # ColumnMapper 9 级策略链
│   ├── schema.py            # SchemaInferrer — 推断列、索引、数据分布
│   ├── relation.py          # RelationResolver + SharedPool — FK 与跨表共享
│   ├── column_dag.py        # ColumnDAG — 列依赖图 + 拓扑排序
│   ├── expression.py        # ExpressionEngine — 安全表达式 (simpleeval + 超时)
│   ├── constraints.py       # ConstraintSolver — 唯一性回溯求解
│   ├── enrichment.py        # EnrichmentEngine — 从既有数据推断分布
│   ├── stream.py            # DataStream — 流式生成 + 约束回溯
│   ├── transform.py         # TransformLoader — 用户脚本动态加载
│   └── result.py            # GenerationResult 数据类
├── generators/              # ===== 数据生成层 =====
│   ├── _protocol.py         # DataProvider Protocol + UnknownGeneratorError
│   ├── _dispatch.py         # GeneratorDispatchMixin.GENERATOR_MAP（36 种）
│   ├── registry.py          # ProviderRegistry (entry-point 自动发现)
│   ├── base_provider.py     # 内置基础生成器；pattern 使用 rstr
│   ├── faker_provider.py    # Faker 适配器
│   └── mimesis_provider.py  # Mimesis 适配器
├── database/                # ===== 数据库层 =====
│   ├── _protocol.py         # DatabaseAdapter Protocol (ColumnInfo, ForeignKeyInfo, IndexInfo)
│   ├── sqlalchemy_adapter.py    # 默认适配器（SQLite/PostgreSQL）
│   ├── raw_sqlite_adapter.py     # 仅供测试的 sqlite3 适配器
│   └── optimizer.py         # PragmaOptimizer 三级优化
├── plugins/                 # ===== 插件层 =====
│   ├── hookspecs.py         # 12 个 pluggy Hook 定义
│   └── manager.py           # PluginManager
├── config/                  # ===== 配置管理 =====
│   ├── models.py            # Pydantic 模型 (GeneratorConfig/TableConfig/ColumnConfig)
│   ├── loader.py            # YAML/JSON 加载与保存
│   └── snapshot.py          # 快照保存与加载
└── _utils/                  # ===== 内部工具 =====
    ├── sql_safe.py          # quote_identifier — SQL 注入防护
    ├── schema_helpers.py    # AUTOINCREMENT 检测
    ├── metrics.py           # MetricsCollector 性能度量
    ├── paths.py             # get_cache_dir — 平台缓存目录
    ├── progress.py          # Rich 进度条
    └── logger.py            # structlog 日志

plugins/
├── sqlseed-cli/             # CLI 插件 — click 命令 (fill/preview/inspect/init/replay)
│   └── src/sqlseed_cli/     # 独立包，单独 pyproject.toml
├── sqlseed-ai/              # AI 插件 — LLM 驱动的智能配置
│   └── src/sqlseed_ai/      # SchemaAnalyzer, AiConfigRefiner, Few-shot 示例...
├── mcp-server-sqlseed/      # MCP 服务器 — AI 助手交互
│   └── src/mcp_server_sqlseed/   # FastMCP 工具 (sqlseed_generate_yaml/sqlseed_execute_fill)
└── sqlseed-web/             # 本地 Web 工作台与可选 AI heal lab
    └── src/sqlseed_web/     # FastAPI 路由、运行时和静态前端
```

***

## 🛠️ 开发

```bash
pytest                              # 运行测试
ruff check src/ tests/ plugins/     # 代码检查
ruff check --fix src/ tests/ plugins/  # 自动修复
mypy                                # 类型检查（按 pyproject.toml 配置，src/ 与 plugins/ 严格模式）
```

### 依赖关系

| 包 | 核心依赖 | 说明 |
|:--|:--------|:-----|
| `sqlseed` | sqlalchemy, pydantic, pluggy, structlog, pyyaml, faker, typing_extensions, simpleeval, rstr, **sqlglot** | Faker 为必需依赖；rstr 生成正则值，sqlglot 解析 CHECK 约束 |
| `sqlseed[mimesis]` | + mimesis>=18.0 | Mimesis 数据引擎（推荐） |
| `sqlseed[postgres]` | + psycopg | PostgreSQL SQLAlchemy 驱动 |
| `sqlseed[docs]` | + mkdocs-material, mkdocstrings | 文档构建 |
| `sqlseed-cli` | sqlseed, **click**, **rich** | CLI 插件 —— 提供 `sqlseed` 命令 (fill/preview/inspect/init/replay)，自动拉取 sqlseed 核心 |
| `sqlseed-ai` | sqlseed, sqlseed-cli, openai>=1.0, httpx>=0.24.0, networkx>=3.0 | AI 插件，通过 entry-point 自动注册 |
| `sqlseed-ai[mcp]` | + mcp>=1.0,<2 | AI MCP 服务器（4 个 LLM 工具）；通过 `pip install "sqlseed-ai[mcp]"` 安装 |
| `mcp-server-sqlseed` | sqlseed, mcp>=1.0,<2 | MCP 服务器（2 个核心工具，无 LLM），独立 CLI 工具 |
| `sqlseed-web` | sqlseed, fastapi>=0.110, uvicorn>=0.29, pyyaml>=6.0, packaging>=23.2 | 本地 Web 工作台；`ai` extra 增加 sqlseed-ai |

***

## 📄 License

[AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE)

***

<div align="center">

**🌱 sqlseed** — *停止手写 fixtures，开始生成数据。*

</div>
