---
hide:
  - navigation
---

# 从现有结构生成测试数据 {#sqlseed}

**为 SQLite 和 PostgreSQL 生成有关联的测试数据。**

sqlseed 向已有表填充数据，自动推断姓名、邮箱等常见字段规则，也支持用 Python 或 YAML
定义业务取值与表间关系。核心引擎离线运行，AI 按需使用。

[了解 Web 工作台](web-workbench.md){ .md-button .md-button--primary }
[从 Python 开始](#generate-your-first-data){ .md-button }

## 选择使用方式 {#choose-how-to-use-it}

在 Python 3.10+ 虚拟环境中安装需要的入口即可。
四个入口插件共用离线核心，安装时会自动带上核心包。

<div class="grid cards sqlseed-entry-cards" markdown>

-   **Python 接口**

    通过 Python 或 YAML 规则，用离线核心生成数据。

    `python -m pip install sqlseed`

    [查看 API 参考 →](api.md)

-   **Web 工作台**

    在浏览器中编辑规则、预览数据并查看运行记录。

    `python -m pip install sqlseed-web`

    [查看工作台指南 →](web-workbench.md)

-   **命令行**

    检查结构、预览、生成数据、创建模板与重放快照。

    `python -m pip install sqlseed-cli`

    [查看命令参考 →](guide.md#cli-reference)

-   **AI 辅助**

    让模型建议、分析或修复规则，再由用户确认使用。

    `python -m pip install sqlseed-ai`

    [配置 AI 服务 →](guide.md#ai-plugin)

-   **MCP 工具**

    通过 MCP 客户端生成规则式 YAML，并执行数据填充。

    `python -m pip install mcp-server-sqlseed`

    [配置 MCP →](guide.md#mcp-server)

-   **支持范围与限制**

    了解数据库支持、约束处理、写入行为与复现条件。

    适用于所有入口，建议在写入数据前阅读。

    [查看支持说明 →](maintainable-release.md)

</div>

AI 插件会安装 CLI，以提供扩展命令；Web 的常规流程无需 AI。
模型辅助的 MCP 工具由 `sqlseed-ai[mcp]` 提供，是独立入口；
`mcp-server-sqlseed` 本身不需要模型服务。

本文档介绍 0.2.5，沿用 0.2.4 引入的五包结构。
发布状态见 [发布记录](https://github.com/sunbos/sqlseed/releases)。
从旧版迁移请先读[升级说明](migration.md)；源码候选与可选依赖见[安装指南](guide.md#installation)。

## 第一次生成数据 {#generate-your-first-data}

安装 `sqlseed` 后，在新目录将以下代码保存为 `demo.py`，运行 `python demo.py`。
它创建 SQLite 表并追加 100 条用户记录，无需克隆仓库或准备数据库服务器：

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

Faker 随核心包安装。每次运行都会追加 100 行，不会清空原表。
请同时检查 `count` 和 `errors`：失败时可能保留先前批次已提交的数据。
约束支持、写入行为和复现条件见[支持范围与限制](maintainable-release.md)。

## 体验浏览器或命令行 {#try-the-browser-or-terminal}

安装 `sqlseed-web` 后运行：

```bash
sqlseed-web
```

打开 [http://127.0.0.1:8630](http://127.0.0.1:8630)，连接 `demo.db`，选择表，编辑规则，先预览再生成。
启动命令随包提供，无需额外启动脚本。工作台支持保存配置、检查表间关系，以及从运行记录查看逐表结果。
界面提供简体中文、英文以及浅色、深色外观。

![sqlseed-web 0.2.5 中文工作台，浅色外观](assets/screenshots/web-workbench-zh-CN-light.png)

0.2.5 正式界面的实际截图。[查看原尺寸 PNG](assets/screenshots/web-workbench-zh-CN-light.png)，
或[查看深色主题下的只读样例预览](assets/screenshots/web-workbench-zh-CN-dark.png)。
安装与操作步骤见 [Web 工作台指南](web-workbench.md)。

安装 `sqlseed-cli` 后，可以对同一个数据库运行：

```bash
sqlseed inspect demo.db --table users --show-mapping
sqlseed preview demo.db -t users -n 5 --provider faker
sqlseed fill demo.db -t users -n 100 --provider faker --no-ai
```

## 继续了解 {#next-steps}

- [使用指南](guide.md)：YAML 规则、生成器、表达式与多表配置。
- [Python API 参考](api.md)：函数、配置模型与返回结果。
- [项目案例讲解](project-showcase.md)：约束处理、失败诊断与重放。
- [AI 配置](guide.md#ai-plugin)：模型设置与可选规则建议。
- [系统架构](architecture.md)：包的职责边界与扩展点。
