# 用户指南 {#user-guide}

本指南介绍安装、快速开始、多数据库连接、CLI、YAML 配置、AI 插件和 MCP 服务器。

完整 Python API 见 [API 参考](api.md)，内部设计见[架构说明](architecture.md)。

---

## 安装 {#installation}

### 安装 0.2.6 版本 {#install-version-025}

本文介绍 0.2.4 引入的五包布局。旧版 0.2.3 的 CLI/MCP 打包方式不同，且缺少新插件需要的接口。[升级指南](migration.md)介绍已有安装的升级方法，以及如何安装相互匹配的构建产物。以下命令面向 0.2.6，请在 [发布记录](https://github.com/sunbos/sqlseed/releases) 中确认发布状态。尚未发布的候选版本使用[源码安装](#source-installation)。

使用新的 Python 3.10+ 虚拟环境，并选择下面的一组安装命令：

```bash
python -m venv .venv
# Activate .venv using your shell's activation command.

# Offline Python API
python -m pip install 'sqlseed==0.2.6'

# Core and CLI
python -m pip install 'sqlseed==0.2.6' 'sqlseed-cli==0.2.6'

# All five packages, AI MCP support, and PostgreSQL driver
python -m pip install 'sqlseed[mimesis,postgres]==0.2.6' 'sqlseed-cli==0.2.6' 'sqlseed-ai[mcp]==0.2.6' 'mcp-server-sqlseed==0.2.6' 'sqlseed-web==0.2.6'
python -m pip check
```

Core 没有控制台命令入口。`sqlseed-cli` 提供 `sqlseed`，`sqlseed-web` 提供 `sqlseed-web`；规则型和 AI MCP 服务器各有独立入口。Core 的 `cli` 选装依赖用于便捷安装 `sqlseed-cli`。

Faker 是 Core 的必需依赖，下面的快速开始会明确选择它。Mimesis 是可选依赖。API 和 CLI 默认使用 `mimesis`；若该引擎不可用，Core 会记录警告并回退到 Base。后续示例中，若省略引擎或选择 Mimesis，请先执行 `python -m pip install 'sqlseed[mimesis]==0.2.6'`，或者在 API、CLI 选项或 YAML 配置中选择 `faker`。

SQLite 使用 Python 内置驱动。`postgres` 选装依赖会安装 psycopg 3。仅安装 Core/Web 的方式见 [Web 指南](web-workbench.md)。Core 的 `all` 选装依赖包含 Mimesis、psycopg、tqdm、CLI 和 testcontainers，不会安装 AI、MCP 或 Web。

### 源码安装 {#source-installation}

克隆仓库，激活 Python 环境，在仓库根目录运行所需命令。在同一条安装命令中列出所有需要的本地包，保证它们来自同一次源码检出：

```bash
git clone https://github.com/sunbos/sqlseed.git
cd sqlseed

# Offline Core
python -m pip install -e .

# Core and CLI
python -m pip install -e . -e ./plugins/sqlseed-cli

# Complete workbench and both MCP servers
python -m pip install -e '.[mimesis,postgres]' -e ./plugins/sqlseed-cli -e './plugins/sqlseed-ai[mcp]' -e ./plugins/mcp-server-sqlseed -e ./plugins/sqlseed-web
python -m pip check
```

以上命令是替代方案，选择其中一组即可。源码可能包含尚未发布的改动。包的发布状态与发行验收方式见[版本列表](https://github.com/sunbos/sqlseed/releases)和[发布指南](releasing.md)。若要在最小源码安装中加入 Mimesis，将所选命令中的 `-e .` 替换为 `-e '.[mimesis]'`。

### 开发与文档 {#development-and-docs}

在仓库根目录同时解析安装 Core 和所有本地插件：

```bash
python -m pip install -e '.[dev,all,docs]' -e ./plugins/sqlseed-cli -e './plugins/sqlseed-ai[dev,mcp]' -e ./plugins/mcp-server-sqlseed -e './plugins/sqlseed-web[dev]'
python -m pip check
pytest
ruff check src/ tests/ plugins/
mypy src/sqlseed/ plugins/
```

`docs` 选装依赖安装 MkDocs Material 和 mkdocstrings。`make docs-build` 使用严格校验构建维护中的文档页面。

---

## 快速开始 {#quick-start}

sqlseed 向已有表中填充数据。第一个示例使用 Python 标准库创建 SQLite 数据库，因此安装 PyPI 包后即可运行，无需克隆仓库。

### Python API 快速开始 {#python-api-quick-start}

在新目录中将以下代码保存为 `quickstart.py`，然后运行 `python quickstart.py`：

```python
from __future__ import annotations

import sqlite3
from contextlib import closing

import sqlseed

with closing(sqlite3.connect("app.db")) as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            age INTEGER NOT NULL CHECK (age BETWEEN 18 AND 65)
        )
    """)
    db.commit()

result = sqlseed.fill(
    "app.db",
    table="users",
    count=100,
    provider="faker",
    seed=42,
    columns={"age": {"type": "integer", "min_value": 18, "max_value": 65}},
)
print(result.count, result.errors)
# 100 []

with closing(sqlite3.connect("app.db")) as db:
    print(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])
# 100 on the first run
```

每次运行都会追加记录。请同时检查 `count` 和 `errors`：某一批次失败时，之前已提交的批次可能保留。详见[写入与失败语义](maintainable-release.md#write-semantics)。

sqlseed 会自动：

- 跳过计算列和显式自增主键。
- 没有更高优先级规则时，将符合条件的默认值列交给数据库处理。
- 根据 `name`、`email`、`age` 等字段名建议生成器；实际取值由显式规则和数据库结构约束共同决定。
- 将 `*_at` 模式匹配为日期时间值。
- 遵守列类型约束，例如 `VARCHAR(20)` 最多生成 20 个字符。

### CLI 快速开始 {#cli-quick-start}

安装 `sqlseed-cli`，使用上面创建的 `app.db`：

```bash
# Preview 5 rows without writing
sqlseed preview app.db --table users --count 5 --provider faker

# Inspect schema and column mapping strategy
sqlseed inspect app.db --show-mapping

# Append 100 rows using the offline provider
sqlseed fill app.db --table users --count 100 --provider faker --no-ai
```

### 试用演示数据库 {#try-the-demo-database}

需要更大的表结构时，可在源码仓库中运行演示：

```bash
python examples/build_demo_db.py

# Populate the parent referenced by members.org_code first.
sqlseed fill examples/sqlseed_demo.db --table organizations --count 10 --provider faker --no-ai
sqlseed preview examples/sqlseed_demo.db --table members --count 5 --provider faker
sqlseed inspect examples/sqlseed_demo.db --show-mapping
sqlseed fill examples/sqlseed_demo.db --table members --count 100 --provider faker --no-ai
```

---

## 多数据库支持 {#multi-database-support}

sqlseed 通过同一套公共 API 支持 SQLite 和 PostgreSQL。不同数据库和调用入口支持的约束、写入模式有所区别；外键限制与部分写入语义见[支持与维护](maintainable-release.md)。

### 连接 URL {#connection-urls}

连接 PostgreSQL 时，传入 SQLAlchemy URL，替代数据库文件路径。

| 数据库 | URL 格式 | 驱动 |
|----------|-----------|--------|
| SQLite | `sqlite:///path/to/db` 或直接使用文件路径 | 内置 `sqlite3` |
| PostgreSQL | `postgresql+psycopg://user:pass@host:5432/db` | `psycopg`（`python -m pip install -e ".[postgres]"`） |

### SQLite

SQLite 是默认数据库后端，无需额外依赖。

```python
import sqlseed

result = sqlseed.fill("app.db", table="users", count=10_000)
```

### PostgreSQL

```bash
python -m pip install -e ".[postgres]"
```



```python
import sqlseed

result = sqlseed.fill(
    url="postgresql+psycopg://user:password@localhost:5432/mydb",
    table="users",
    count=10_000,
)
```

---

## CLI 参考 {#cli-reference}

`sqlseed-cli` 提供五个子命令：`fill`、`preview`、`inspect`、`init` 和 `replay`。安装 `sqlseed-ai` 后会增加 `ai-suggest`、`ai-analyze` 和 `auto-heal`，完整安装共提供八个命令。运行 `sqlseed --help` 查看完整列表，或运行 `sqlseed <command> --help` 查看对应命令的选项。

### `fill`

向一张表中填充生成的测试数据。

```bash
# Basic usage
sqlseed fill app.db --table users --count 10000

# Full parameters
sqlseed fill app.db -t users -n 100000 \
    --provider mimesis \
    --locale en_US \
    --seed 42 \
    --batch-size 10000 \
    --enrich \
    --snapshot

# YAML config-driven (count from config file)
sqlseed fill --config generate.yaml

# Transform script
sqlseed fill app.db -t users -n 10000 --transform transform.py

# Connect via URL instead of file path
sqlseed fill --url "postgresql+psycopg://user:pass@host/db" -t users -n 1000

# Enable debug logging
SQLSEED_LOG_LEVEL=DEBUG sqlseed fill app.db -t users -n 10
```

**选项**

| 选项 | 说明 |
|--------|-------------|
| `--table, -t` | 目标表名 |
| `--count, -n` | 生成行数（未使用 `--config` 时必填） |
| `--provider, -p` | `mimesis` / `faker` / `base`（默认：`mimesis`） |
| `--locale, -l` | 数据语言地区（默认：`en_US`） |
| `--seed, -s` | 用于复现结果的随机种子 |
| `--batch-size, -b` | 每批插入行数（默认：`5000`） |
| `--clear` | 生成前清空表 |
| `--config, -c` | YAML/JSON 配置文件路径 |
| `--transform` | Python 转换脚本路径 |
| `--snapshot` | 保存生成快照供重放使用 |
| `--enrich` | 根据已有数据推断分布 |
| `--no-ai` | 跳过 AI 建议 |
| `--url` | 数据库 URL（替代位置参数 `db_path`） |

如果 `--config` 指定的文件无法读取、解析或通过配置校验，`fill` 会显示原因，并在生成或清表前以状态码 2 退出。请修正文件路径、UTF-8 YAML/JSON 语法或提示的字段，再重试同一命令。

### `preview`

预览生成数据，不写入数据库。

```bash
sqlseed preview app.db --table users --count 5
sqlseed preview --url "postgresql+psycopg://user:pass@host/db" --table users --count 10
```

**选项**

| 选项 | 说明 |
|--------|-------------|
| `--table, -t` | 目标表名（必填） |
| `--count, -n` | 预览行数（默认：`5`） |
| `--provider, -p` | 数据生成引擎（默认：`mimesis`） |
| `--locale, -l` | 数据语言地区（默认：`en_US`） |
| `--seed, -s` | 随机种子 |
| `--url` | 数据库 URL |

### `inspect`

检查数据库结构与字段映射策略。

```bash
# List all tables
sqlseed inspect app.db

# Inspect a specific table
sqlseed inspect app.db --table users

# View column mapping strategy
sqlseed inspect app.db --table users --show-mapping
```

**选项**

| 选项 | 说明 |
|--------|-------------|
| `--table, -t` | 要检查的具体表 |
| `--show-mapping` | 显示字段映射策略 |
| `--url` | 数据库 URL |

### `init`

使用数据库中的表名，生成基本的 YAML 配置骨架。

```bash
sqlseed init generate.yaml --db app.db
```

模板包含发现的表名、默认生成数量和空的 `columns` 列表。按需添加显式字段规则；未提供的规则会在生成时推断。`--url` 接受数据库 URL，与 `--db` 互斥。两个选项都不提供时，默认目标为 `test.db`。

### `replay`

快照文件不存在、无法读取或格式损坏时，命令会在开始生成前显示诊断信息并以状态码 2 退出。请检查文件路径、读取权限和 UTF-8 YAML 语法。

重放快照中保存的生成配置。比较生成值时，应使用表结构、生成引擎和依赖版本、随机种子、固定时间范围、初始父表数据均一致的新数据库。向已有数据的数据库重放可能遇到 UNIQUE 冲突；配置快照不是数据库备份。详见[复现条件](maintainable-release.md#reproduction-conditions)。

```bash
# Generate and save snapshot
sqlseed fill app.db --table users --count 10000 --seed 42 --snapshot
# → Snapshot saved: <cache_dir>/snapshots/YYYY-MM-DD_HHMMSS_ffffff_users.yaml

# Replace this path with the actual snapshot path printed by fill.
sqlseed replay "/path/to/saved-snapshot.yaml"
```

适用场景：

- 在 CI/CD 流水线中复现测试数据。
- 为团队提供一致的测试环境。
- 在开发过程中复用已审阅的生成设置。

### `ai-suggest`

通过大语言模型分析数据库结构，生成 YAML 配置建议。需要安装 `sqlseed-ai` 插件。

```bash
# Install a compatible AI/CLI/Core set as described under Installation

# Select the cloud backend explicitly
export SQLSEED_AI_BACKEND=google_ai_studio
export SQLSEED_AI_API_KEY="your-api-key"

# AI analysis and config generation
sqlseed ai-suggest app.db --table projects --output projects.yaml

# Self-correction is enabled by default (up to 3 retries)
sqlseed ai-suggest app.db --table projects --output projects.yaml --verify

# Specify a model available from the selected backend
sqlseed ai-suggest app.db --table projects --output projects.yaml \
    --model gemma-4-26b-a4b-it

# Use local LM Studio / Ollama (backend selected via environment variable)
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table projects --output projects.yaml \
    --model google/gemma-4-e4b

# Skip cache
sqlseed ai-suggest app.db --table projects --output projects.yaml --no-cache
```

**选项**

| 选项 | 说明 |
|--------|-------------|
| `--table, -t` | 目标表名 |
| `--output, -o` | 输出 YAML 文件路径 |
| `--verify` | 启用自我修正循环（默认启用） |
| `--max-retries` | 自我修正轮数（默认：`3`；`0` 表示禁用） |
| `--no-verify` | 跳过验证 |
| `--no-cache` | 跳过缓存 |
| `--api-key` | 模型 API 密钥（覆盖 `SQLSEED_AI_API_KEY`） |
| `--base-url` | 模型 API 基础 URL |
| `--model, -m` | 模型名称（省略时按配置的后端自动选择） |
| `--timeout` | 请求超时秒数（`0` 表示自动选择） |
| `--auto-heal` | 使用契约驱动的自我修复处理所有表；忽略 `--table` 和 `--output` |

通过 `SQLSEED_AI_BACKEND` 或可识别的基础 URL 选择后端。AI CLI 命令不接受 `--backend` 选项。

调用模型前，目标表必须已经存在。建议和缓存结果必须对应同一张表；允许 SQLite 的 ASCII 大小写别名，但会拒绝不同的表。导出时保留真实表名和列名，包括开头的 `.` 或 `:` 字符。这些身份检查也适用于 `--no-verify` 和 `--max-retries 0`：这两个选项跳过生成验证，不会取消目标保护。被拒绝的建议不会替换已有输出文件。

提示词要求只为指定表返回一个 JSON 对象，并保留其表名和列名。结构中的其他表名只是引用上下文，不是额外的输出目标。提示词要求不能替代目标验证。

直接分析（`--no-verify` 或 `--max-retries 0`）在流式与非流式模式下，都会区分空响应、无效 JSON、输出长度截断以及空配置对象，诊断信息不会回显模型响应。只有现有的缩短提示词序列还有下一级时才会重试；最后一级会报告具体失败并以失败状态退出，不会声称还要重试。这一过程不会扩展该序列或增加请求预算。拒绝响应后，已有输出 YAML 和数据库均保持不变。

Python 调用方可通过 `SchemaAnalyzer.call_llm(..., strict_json=True)` 或 `call_llm_streaming(..., strict_json=True)` 启用相同诊断。两个方法的默认值仍为 `False`。严格流式模式会拒绝 `finish_reason=length`，即使该状态位于独立的空终止分块中，且之前的 JSON 可以解析。底层 Python 流式调用并不会因此默认全部启用严格模式。`AiConfigRefiner` 的流式和非流式调用均明确启用严格响应处理，默认 CLI 验证路径也包含在内。即使被截断响应的 JSON 前缀可以修复并通过生成验证，仍会拒绝该响应；现有重试预算和输出文件保留规则不变。非对象类型的工具参数会得到相同的安全格式诊断。格式错误的建议缓存封装按缓存未命中处理，随后正常重新生成。

### `ai-analyze`

分析数据库或指定表，并写出 YAML 规则。该命令默认使用 `AutoHealOrchestrator`，与单表的 `ai-suggest`/`AiConfigRefiner` 路径不同。

```bash
sqlseed ai-analyze --db app.db -o rules.yaml
sqlseed ai-analyze --db app.db --tables orders,order_items -o rules.yaml
sqlseed ai-analyze --url 'postgresql+psycopg://user:pass@host/db' -o rules.yaml
```

`--db` 与 `--url` 互斥。`--no-dependencies` 将分析限制为选中的表；`--max-depth` 默认为 `5`。`--merge` 更新已有输出文件中的选中表，并且要求提供 `--output`。没有 `--output` 时，YAML 写入标准输出。模型选项为 `--model`、`--api-key`、`--base-url` 和 `--timeout`；`--max-retries` 默认为 `2`。`--log-llm` 保存提示词和响应日志供诊断使用。

### `auto-heal`

通过契约驱动的自我修复，修正已有 YAML 配置：

```bash
sqlseed auto-heal --db app.db --config rules.yaml -o rules_healed.yaml
```

必须提供 `--config`，并在 `--db` 和 `--url` 中选择一个目标选项。这两个目标选项互斥，用于设置所提供配置的执行目标。`--output` 默认为 `<config>_healed.yaml`。`--max-retries` 默认为 `3`；`--model`、`--api-key`、`--base-url` 和 `--log-llm` 用于配置模型和日志。执行前应审阅结果规则并进行预览。

---

## YAML 配置 {#yaml-configuration}

复杂的多表场景可以使用 YAML 配置文件，这是 sqlseed 功能最完整的配置方式。

### 基本结构 {#basic-structure}

以下示例向已有的 `users` 和 `orders` 表追加数据。示例假设 `users` 包含 `id`、`name` 和 `email`，且 `orders.user_id` 引用 `users.id`。

`clear_before` 默认为 `false`。若子记录已经引用父记录，先清空父表可能失败，而后续表仍可能追加数据。请使用结构相同的新数据库，或明确先清空依赖的子表，再清空父表。仅靠生成顺序不能安全清空已有外键关系图；请检查每个结果的 `count` 和 `errors`。

```yaml
# generate.yaml
db_path: "app.db"           # SQLite file path (mutually exclusive with url)
# url: "postgresql+psycopg://user:pass@host/db"  # Mutually exclusive with db_path
provider: mimesis            # mimesis | faker | base | custom
locale: en_US
optimize_pragma: true

tables:
  - name: users
    count: 100000
    batch_size: 10000
    seed: 42
    columns:
      - name: name
        generator: name
      - name: email
        generator: email

  - name: orders
    count: 500000
    columns:
      - name: user_id
        generator: foreign_key
        params:
          ref_table: users
          ref_column: id
          strategy: random

associations: []             # Cross-table column associations
```

### 字段映射 {#column-mapping}

每个字段可以采用以下两种互斥的配置模式：

**来源列模式**：指定 `generator` + `params`：

```yaml
columns:
  - name: email
    generator: email
  - name: age
    generator: integer
    params:
      min_value: 18
      max_value: 65
  - name: status
    generator: choice
    params:
      choices: [active, inactive, banned]
    null_ratio: 0.05         # 5% chance of NULL
```

**派生列模式**：指定 `derive_from` + `expression`：

```yaml
columns:
  - name: project_no
    generator: pattern
    params:
      regex: "PRJ-\\d{6}"
    constraints:
      unique: true

  - name: short_code
    derive_from: project_no    # depends on project_no
    expression: "value[-6:]"  # last 6 chars
    constraints:
      unique: true
```

sqlseed 会构建列依赖有向无环图（DAG），并在生成前对字段进行拓扑排序。如果派生列的唯一约束失败，会回溯并重新生成来源列。

### 生成器 {#generators}

sqlseed 内置 <!-- BEGIN:AUTO-GENERATED:generator-count -->36<!-- END:AUTO-GENERATED:generator-count --> 个生成器。下面的完整列表还包含 `foreign_key` 和 `skip`，它们由编排层单独处理。

| 生成器 | 说明 | 参数示例 |
|-----------|-------------|-------------------|
| `string` | 随机字符串 | `min_length`, `max_length`, `charset` |
| `integer` | 整数 | `min_value`, `max_value` |
| `float` | 浮点数 | `min_value`, `max_value`, `precision` |
| `boolean` | 布尔值 | — |
| `name` | 完整姓名 | — |
| `first_name` | 名 | — |
| `last_name` | 姓 | — |
| `email` | 电子邮件地址 | — |
| `phone` | 电话号码 | — |
| `address` | 地址 | — |
| `company` | 公司名称 | — |
| `url` | URL | — |
| `ipv4` | IPv4 地址 | — |
| `uuid` | UUID | — |
| `date` | 日期 | `start_date`, `end_date`, `weekdays` |
| `datetime` | 日期时间 | `start_date`, `end_date`, `all_day`, `start_time`, `end_time`, `weekdays` |
| `time` | 时间 | `all_day`, `start_time`, `end_time` |
| `timestamp` | Unix 时间戳 | 与 `datetime` 相同 |
| `text` | 长文本 | `min_length`, `max_length` |
| `sentence` | 句子 | — |
| `word` | 真实英文单词 | — |
| `password` | 密码 | `length` |
| `choice` | 从列表中选择 | `choices` |
| `json` | JSON 字符串 | `schema` |
| `pattern` | 正则匹配 | `regex` |
| `bytes` | 二进制数据 | `length` |
| `username` | 用户名 | — |
| `city` | 城市 | — |
| `country` | 国家 | — |
| `state` | 州或省 | — |
| `zip_code` | 邮政编码 | — |
| `job_title` | 职位名称 | — |
| `country_code` | 国家代码 | — |
| `catch_phrase` | 商业宣传语（多个单词） | — |
| `template` | 带占位符的格式化字符串 | `template`, `sequence_start`, `sequence_step` |
| `weighted_choice` | 按权重随机选择 | `choices`（`{value, weight}` 列表）或 `weighted_choices`（字典） |
| `foreign_key` | 外键引用 | `ref_table`, `ref_column`, `strategy` |
| `skip` | 跳过（使用默认值或 NULL） | — |

`float` 生成器将 `min_value` 和 `max_value` 视为包含端点的边界，按 `precision` 保留小数位后也必须满足该范围。边界顺序颠倒或包含非有限数值时会抛出 `ValueError`。如果范围内没有符合指定精度的值（例如范围为 `0.005`–`0.006` 且 `precision: 2`），会抛出 `ValueError`，而不是返回超出范围的值。

`foreign_key` 和 `skip` 是特殊的伪生成器：由 `RelationResolver` / `DataStream` 直接处理，不注册到 `GENERATOR_MAP` 中。

### 约束 {#constraints}

每列的约束放在 `constraints` 下：

```yaml
columns:
  - name: project_no
    generator: pattern
    params:
      regex: "PRJ-\\d{6}"
    constraints:
      unique: true             # enforce uniqueness with backtracking
      max_retries: 100         # default: 100
  - name: age
    generator: integer
    constraints:
      min_value: 18
      max_value: 65
```

### 表达式 {#expressions}

表达式引擎支持 26 个安全函数，以及切片和基本算术运算。表达式通过 `simpleeval` 在沙箱中执行，超时为 5 秒。不允许 `import`、`exec` 和文件 I/O。

| 函数 | 用法 | 说明 |
|----------|-------|-------------|
| `len(s)` | `len(value)` | 长度 |
| `int(s)` | `int(value)` | 转为整数 |
| `str(s)` | `str(value)` | 转为字符串 |
| `float(s)` | `float(value)` | 转为浮点数 |
| `hex(n)` | `hex(value)` | 转为十六进制 |
| `oct(n)` | `oct(value)` | 转为八进制 |
| `bin(n)` | `bin(value)` | 转为二进制 |
| `abs(n)` | `abs(value)` | 绝对值 |
| `min(*args)` | `min(a, b)` | 最小值 |
| `max(*args)` | `max(a, b)` | 最大值 |
| `round(n, ndigits)` | `round(value, 2)` | 舍入到指定小数位 |
| `upper(s)` | `upper(value)` | 转为大写 |
| `lower(s)` | `lower(value)` | 转为小写 |
| `strip(s)` | `strip(value)` | 去除两端空白 |
| `lstrip(s)` | `lstrip(value)` | 去除左侧空白 |
| `rstrip(s)` | `rstrip(value)` | 去除右侧空白 |
| `zfill(s, width)` | `zfill(value, 10)` | 补零 |
| `replace(s, old, new)` | `replace(value, "-", "")` | 替换 |
| `substr(s, start, end)` | `substr(value, 0, 8)` | 子字符串 |
| `lpad(s, width, char)` | `lpad(value, 8, "0")` | 左侧填充 |
| `rpad(s, width, char)` | `rpad(value, 8, "0")` | 右侧填充 |
| `concat(*args)` | `concat("PRE_", value)` | 拼接 |
| `random_float(min, max)` | `random_float(0, value)` | 范围内的随机浮点数 |
| `random_int(min, max)` | `random_int(1, 100)` | 范围内的随机整数 |
| `random_choice(seq)` | `random_choice([1,2,3])` | 从序列中随机选择元素 |
| `timedelta(...)` | `value + timedelta(days=7)` | 日期运算（`days`/`seconds`/`hours`/`minutes`/`weeks`） |
| 切片 | `value[-8:]` | Python 切片语法 |
| 数学运算 | `value * 2 + 1` | 基本算术运算 |

### 跨表关联 {#cross-table-associations}

**SharedPool** 可以复用当前编排会话中已注册的主键和外键列值。仅仅让普通列同名（例如 `member_no`）不会建立关联。非外键的 UNIQUE 目标列也不会隐式复用取值。

数据库中已声明的关系应使用真实外键。若关系没有通过外键表示，需要在 `associations` 中显式声明来源表、来源列和目标表：

例如，先创建以下表，再运行配置。关系由配置声明，下面的 DDL 没有外键约束：

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
  - name: employees
    count: 20

associations:
  - column_name: department_id     # column name in the target table
    source_table: departments      # source table providing values
    source_column: id              # column name in source table (defaults to column_name)
    target_tables:                 # target tables using this association
      - employees
    strategy: shared_pool          # shared_pool | random
```

### 转换脚本 {#transform-scripts}

无法用声明式规则表达的复杂业务逻辑，可以编写 Python 转换脚本。

下面的脚本要求已有 `users` 表包含 `age` 和 `phone` 列。生成数据前，先添加用于存储结果的列：

```sql
ALTER TABLE users ADD COLUMN vip_level INTEGER;
```



```python
# transform_users.py
def transform_row(row, ctx):
    """Called for every generated row."""
    age = row.get("age", 0)
    if age >= 60:
        row["vip_level"] = 3
    elif age >= 40:
        row["vip_level"] = 2
    else:
        row["vip_level"] = 1

    phone = row.get("phone", "")
    if phone and not phone.startswith("+1"):
        row["phone"] = f"+1{phone}"

    return row
```

通过 CLI 使用：

```bash
sqlseed fill app.db --table users --count 10000 --transform transform_users.py
```

也可以在 YAML 中配置：

```yaml
db_path: "app.db"
tables:
  - name: users
    count: 10000
    transform: "./transform_users.py"
```

---

## AI 插件 {#ai-plugin}

`sqlseed-ai` 插件使用大语言模型分析数据库结构的语义，自动生成 YAML 配置建议，并支持自我修正循环。

### 配置 {#setup}

按[安装说明](#installation)安装兼容的 Core/CLI/AI 包集合。明确选择一个后端，或提供可用于识别后端的基础 URL：

```bash
# Google AI Studio
export SQLSEED_AI_BACKEND=google_ai_studio
export GOOGLE_API_KEY="your-api-key"

# Alternatively, configure an OpenAI-compatible endpoint
# export SQLSEED_AI_BACKEND=openai_compat
# export SQLSEED_AI_BASE_URL="https://your-provider.example/v1"
# export SQLSEED_AI_MODEL="your-model-id"
# export SQLSEED_AI_API_KEY="your-api-key"
```

### 使用方法 {#usage}

```bash
# Basic AI suggestion
sqlseed ai-suggest app.db --table projects --output projects.yaml

# With self-correction loop (3 rounds by default)
sqlseed ai-suggest app.db --table projects --output projects.yaml --verify

# Disable self-correction
sqlseed ai-suggest app.db --table projects --output projects.yaml --max-retries 0
```

### 后端 {#backends}

sqlseed-ai 支持以下后端。显式的 `SQLSEED_AI_BACKEND` 优先级最高，其次根据可识别的基础 URL 模式判断；否则使用 `openai_compat`，此时需要明确提供基础 URL。仅设置 Google API 密钥不会选中 Google AI Studio。

| 后端 | 说明 | 适用模型 |
|---------|-------------|--------------|
| `google_ai_studio` | 明确选择 Google AI Studio API | 该服务提供的模型 |
| `lm_studio` | 通过 LM Studio 本地推理 | Gemma 4 2B/4B |
| `ollama` | 通过 Ollama 本地推理 | Gemma 4 2B/4B/26B |
| `openai_compat` | 通用 OpenAI 兼容端点；默认回退后端 | 配置端点提供的模型 |

模型 ID 取决于后端。未指定时，本地后端会先尝试检测已加载模型，再回退到本地 Gemma E4B；云端后端使用项目为该后端注册的 Gemma 26B 模型 ID。项目注册了某个 ID，并不保证服务当前提供该模型。必要时请明确指定可用模型，并用小请求验证。

### 环境变量 {#environment-variables}

| 变量 | 说明 |
|----------|-------------|
| `SQLSEED_AI_API_KEY` | 模型 API 密钥 |
| `SQLSEED_AI_BASE_URL` | 模型 API 基础 URL |
| `SQLSEED_AI_MODEL` | 明确指定模型 ID；否则根据已解析的后端选择 |
| `SQLSEED_AI_BACKEND` | 明确指定后端；没有可识别 URL 时回退到 `openai_compat` |
| `SQLSEED_AI_TOOL_CALLING_PROTOCOL` | `gemma4`、`openai` 或 `none`；按后端支持情况解析 |
| `SQLSEED_AI_TIMEOUT` | 请求超时秒数（`0` 表示自动选择） |
| `GOOGLE_API_KEY` | API 密钥备用来源，优先级低于 `SQLSEED_AI_API_KEY`、高于 `OPENAI_API_KEY` |
| `OPENAI_API_KEY` | 备用 API 密钥 |
| `OPENAI_BASE_URL` | 备用基础 URL |

### AI 工作流程 {#ai-workflow}

单表 `ai-suggest` 路径使用 `SchemaAnalyzer` 和 `AiConfigRefiner`：

1. 提取结构上下文（列、索引、样例数据、外键、分布）。
2. 使用少样本示例构建模型提示词。
3. 模型返回 JSON 格式的字段配置建议。
4. `AiConfigRefiner` 自动验证配置是否正确。
5. 发现未知生成器、类型不匹配等错误时，向模型发送修正请求。
6. 最多进行 3 轮自我修正，输出经过验证的 YAML 配置。

`ai-analyze` 和 `auto-heal` 使用 `AutoHealOrchestrator` 进行契约驱动的分析或修复。Web 助手提供待审阅的建议，不会自动执行已接受的规则或运行 CLI。

Gemma 4 原生函数调用的详细说明见 [Gemma 4 集成](gemma4-integration.md)。

---

## MCP 服务器 {#mcp-server}

`mcp-server-sqlseed` 通过[模型上下文协议](https://modelcontextprotocol.io/)（Model Context Protocol），向 Claude、Cursor 等 AI 助手开放 sqlseed 能力。

### 配置 {#setup_1}

使用[安装说明](#installation)中的兼容包集合。规则型服务器由 `mcp-server-sqlseed` 提供；AI 服务器需要 `sqlseed-ai[mcp]`。它们是独立进程。安装 AI 包不会向已配置的规则型服务器自动添加工具。

```bash
# Rule-driven server (offline)
mcp-server-sqlseed

# AI server (a separate process, normally started by the MCP client)
mcp-server-sqlseed-ai
```

### 配置 MCP 客户端 {#configure-mcp-client}

同时使用两组工具的客户端需要配置两个服务器入口。例如，在 Claude Desktop 的 `claude_desktop_config.json` 中：

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    },
    "sqlseed-ai": {
      "command": "mcp-server-sqlseed-ai",
      "env": {
        "SQLSEED_AI_BACKEND": "lm_studio",
        "SQLSEED_AI_MODEL": "google/gemma-4-e4b"
      }
    }
  }
}
```

如果客户端找不到命令，请使用所选环境中的可执行文件路径。上面的 AI 示例要求 LM Studio 服务可访问，且已加载配置的模型。使用云端或其他后端时，按前面的 AI 配置说明替换环境变量；MCP 进程能够运行不代表模型连接已验证。

### 工具 {#tools}

基础 `mcp-server-sqlseed` 包提供两个规则型工具（不调用大语言模型）：

| 类型 | 名称 | 说明 |
|------|------|-------------|
| 🤖 工具 | `sqlseed_generate_yaml` | 通过 `ColumnMapper` 按规则生成 YAML 配置（离线、确定性、不调用模型） |
| ⚡ 工具 | `sqlseed_execute_fill` | 执行数据生成（支持 YAML 配置字符串，包含 `enrich`） |

两个工具均使用 Faker 和 `en_US`，与生成的 YAML 模板一致。工具参数决定数据库、表、行数和分布推断选项。YAML 仅提供请求表的字段规则、随机种子和 `clear_before`；顶层 provider 和 locale 设置不会改变服务器的生成引擎或语言地区。详见 [Core MCP 参考](https://github.com/sunbos/sqlseed/blob/main/plugins/mcp-server-sqlseed/README.zh-CN.md#mcp-tools)。

独立的 `mcp-server-sqlseed-ai` 进程提供四个 AI 工具：

| 类型 | 名称 | 说明 |
|------|------|-------------|
| 🤖 工具 | `sqlseed_ai_generate_yaml` | 模型驱动的 YAML 配置生成（数据库结构语义分析） |
| 🧠 工具 | `sqlseed_gemma4_analyze` | 使用配置的模型和受支持的响应协议分析结构 |
| 🧠 工具 | `sqlseed_gemma4_agent_fill` | 端到端 Agent 工作流（分析 → 配置 → 填充） |
| 🧠 工具 | `sqlseed_list_gemma_models` | 列出已注册的 Gemma 4 变体、硬件兼容性和后端状态 |

### 交互示例 {#example-interaction}

配置完成后，可以对 AI 助手说：

> “分析 `app.db` 中 `projects` 表的结构，生成 YAML 配置，然后填充 5000 行。”

配置两个服务器后，助手可以从 `sqlseed_ai_generate_yaml` 获取规则，并将审阅后的规则提交给 `sqlseed_execute_fill`。仅配置规则型服务器时，使用 `sqlseed_generate_yaml` 获取离线规则。请求填充前，请审阅数据库目标和规则。

---

## 九级智能字段映射 {#9-level-smart-column-mapping}

`ColumnMapper` 的九级策略链是 sqlseed 的核心能力之一。每列按以下优先级匹配：

```
Level 1 │ Computed / explicit autoincrement PK → skip
        ▼
Level 2 │ Explicit user config
        ▼
        │ SQLite rowid alias → skip; other integer PK → type fallback
        ▼
Level 3 │ Exact match         Custom rules, then 75 built-in rules
        ▼
Level 4 │ DEFAULT handling    skip / __enrich__ / forced type inference
        ▼
Level 5 │ Pattern match       Custom rules, then 29 built-in patterns
        ▼
Level 6 │ Snake-case retry    Convert CamelCase, retry exact rules
        ▼
Level 7 │ Snake-case retry    Retry pattern rules
        ▼
Level 8 │ NULLABLE fallback   skip / __enrich__ / forced type inference
        ▼
Level 9 │ Type fallback       Preserve declared string and byte lengths
```

适配器会区分 SQLite rowid 别名主键与复合主键、降序主键、WITHOUT ROWID 主键。仅凭名称类似 ID 不会建立外键关系。在精确匹配和模式匹配内部，自定义规则优先于内置规则。

实际示例：

- `user_email` → 第 5 级模式 `*_email` → `email` 生成器。
- `is_verified` → 第 5 级模式 `is_*` → `boolean` 生成器。
- `userEmail` → 转换为蛇形命名重试 → `user_email` → 第 7 级模式匹配。
- 未匹配的非空 `VARCHAR(20)` → 第 9 级 → 最多 20 个字符的字符串。
- 带 `DEFAULT 1` 且未匹配更高优先级规则的列 → 第 4 级 → 跳过生成。
- 带 `DEFAULT 'male'` 的 `gender` → 第 3 级精确匹配 → `choice`（优先于 DEFAULT）。

---

## 插件系统 {#plugin-system}

sqlseed 通过 [pluggy](https://pluggy.readthedocs.io/) 声明 12 个 Hook 契约。当前调用时机如下；声明了 Hook 不代表常规生成流程一定会调用它。

| Hook | firstresult | 触发时机 |
|------|:-----------:|--------|
| `sqlseed_register_providers` | | 注册自定义数据生成引擎 |
| `sqlseed_register_column_mappers` | | 注册自定义字段映射规则 |
| `sqlseed_ai_analyze_table` | ✓ | AI 分析表结构（返回字段配置） |
| `sqlseed_apply_ai_suggestions` | ✓ | 高层 AI 协调（编排器入口；实现在 `sqlseed_ai.ai_mediator`） |
| `sqlseed_pre_generate_templates` | ✓ | AI 预先计算候选值池 |
| `sqlseed_before_generate` | | 数据生成循环开始前 |
| `sqlseed_after_generate` | | 数据生成完成后 |
| `sqlseed_transform_row` | | 已声明 Hook 规范；常规 Core 生成流程不调用 |
| `sqlseed_transform_batch` | | 每个实现接收同一输入批次；选用最后一个非 None 结果 |
| `sqlseed_before_insert` | | 每批数据写入数据库前 |
| `sqlseed_after_insert` | | 每批数据写入数据库后 |
| `sqlseed_shared_pool_loaded` | | SharedPool 注册完成后（此时可以读取值池） |

### 自定义数据生成引擎示例 {#custom-provider-example}

```python
# my_provider.py
from __future__ import annotations
from typing import Any

from sqlseed.generators import UnknownGeneratorError

class MyCustomProvider:
    """Just implement the DataProvider Protocol. No base class required."""

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

**通过入口点注册（推荐）：**

```toml
# pyproject.toml
[project.entry-points."sqlseed"]
my_custom = "my_provider:MyCustomProvider"
```

**通过插件 Hook 注册：**

```python
from sqlseed.plugins.hookspecs import hookimpl

class MyPlugin:
    @hookimpl
    def sqlseed_register_providers(self, registry):
        from my_provider import MyCustomProvider
        registry.register(MyCustomProvider())
```

---

## 故障排查 {#troubleshooting}

### 启用调试日志 {#enable-debug-logging}

```bash
SQLSEED_LOG_LEVEL=DEBUG sqlseed fill app.db -t users -n 10
```

### 常见问题 {#common-issues}

**`--count is required when not using --config`**

使用 `sqlseed fill` 且未提供 `--config` 时，需要提供 `--count`（或 `-n`）。

**`Cannot specify both positional db_path and --url`**

`db_path` 与 `--url` 互斥，只能选择一个。

**`Table does not exist`**

先使用 `sqlseed inspect app.db` 检查数据库，核对表名及反射得到的实际拼写。标识符大小写处理取决于数据库和引用规则，不能仅根据操作系统判断。

**`Unknown generator: <name>`**

对照上面的[生成器列表](#generators)检查名称。自定义生成器必须通过入口点或插件 Hook 注册。

**未找到 AI 插件**

按[安装指南](#installation)安装兼容的 Core/CLI/AI 包集合。源码安装时，在同一条命令中提供三个本地包：

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e ./plugins/sqlseed-ai
```

未安装 `sqlseed-ai` 时，`sqlseed ai-suggest` 会返回 Click 的 `No such command` 错误。若插件已安装但加载失败，CLI 会输出 `WARNING` 日志。

---

## 后续阅读 {#next-steps}

- [API 参考](api.md)：完整 Python API 文档。
- [架构说明](architecture.md)：内部设计与模块结构。
- [Gemma 4 集成](gemma4-integration.md)：AI 结构分析配置。
