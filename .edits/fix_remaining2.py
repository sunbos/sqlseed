"""Fix remaining stale docs in /tmp/wt-multi-db."""
from __future__ import annotations
import sys
sys.path.insert(0, "/workspace")
from _edit_helper import edit

ROOT = "/tmp/wt-multi-db"

# ---- README.md MySQL removal & table/tree fixes ----
edit(f"{ROOT}/README.md",
     "Declarative SQLite test data generation toolkit. YAML/JSON config or Python API.",
     "Declarative Multi-Database test data generation toolkit. YAML/JSON config or Python API.")

edit(f"{ROOT}/README.md",
     "In development and testing workflows, we often need to populate SQLite, PostgreSQL, and MySQL databases with large volumes of realistic test data.",
     "In development and testing workflows, we often need to populate SQLite and PostgreSQL databases with large volumes of realistic test data.")

edit(f"{ROOT}/README.md",
     "sqlseed supports SQLite (default), PostgreSQL, and MySQL via SQLAlchemy.",
     "sqlseed supports SQLite (default) and PostgreSQL via SQLAlchemy. MySQL support was removed (deferred until PostgreSQL is fully validated).")

edit(f"{ROOT}/README.md",
     "# MySQL support (mysqlclient driver)\npip install \"sqlseed[mysql]\"",
     "")

edit(f"{ROOT}/README.md",
     "# All database backends + all data engines\npip install \"sqlseed[all]\"",
     "# All database backends + all data engines + testcontainers\npip install \"sqlseed[all]\"")

edit(f"{ROOT}/README.md",
     "> **💡 Note**: SQLite works out of the box with no extra dependencies. PostgreSQL/MySQL drivers are only required when connecting to those databases.",
     "> **💡 Note**: SQLite works out of the box with no extra dependencies. PostgreSQL driver is only required when connecting to PostgreSQL.")

edit(f"{ROOT}/README.md",
     "### Connect to PostgreSQL / MySQL",
     "### Connect to PostgreSQL")

edit(f"{ROOT}/README.md",
     "sqlseed supports PostgreSQL and MySQL in addition to SQLite. Pass a SQLAlchemy URL instead of a file path:",
     "sqlseed supports PostgreSQL in addition to SQLite. Pass a SQLAlchemy URL instead of a file path:")

edit(f"{ROOT}/README.md",
     "# MySQL (requires: pip install \"sqlseed[mysql]\")\nresult = sqlseed.fill(\n    \"mysql+mysqldb://user:password@localhost:3306/mydb\",\n    table=\"users\",\n    count=10_000,\n)\nprint(result)\n```",
     "```")

edit(f"{ROOT}/README.md",
     "The same API works for all three databases — schema inference, FK resolution, expression engine, and plugin hooks all run identically across SQLite, PostgreSQL, and MySQL.",
     "The same API works for both databases — schema inference, FK resolution, expression engine, and plugin hooks all run identically across SQLite and PostgreSQL.")

edit(f"{ROOT}/README.md",
     "│   ├── sqlalchemy_adapter.py    # Default adapter (SQLite/PostgreSQL/MySQL)",
     "│   ├── sqlalchemy_adapter.py    # Default adapter (SQLite/PostgreSQL)")

edit(f"{ROOT}/README.md",
     "├── cli/                     # ===== CLI =====\n│   └── main.py              # click commands (fill/preview/inspect/init/replay/ai-suggest)",
     "")

edit(f"{ROOT}/README.md",
     "| `sqlseed[mysql]` | + mysqlclient | MySQL driver for SQLAlchemy |",
     "")

# ---- README.zh-CN.md ----
edit(f"{ROOT}/README.zh-CN.md",
     "声明式 SQLite 测试数据生成工具包。YAML/JSON 配置或 Python API。",
     "声明式多数据库测试数据生成工具包。YAML/JSON 配置或 Python API。")

edit(f"{ROOT}/README.zh-CN.md",
     "在开发与测试工作流中，我们经常需要为 SQLite、PostgreSQL、MySQL 数据库填充大量真实测试数据。",
     "在开发与测试工作流中，我们经常需要为 SQLite、PostgreSQL 数据库填充大量真实测试数据。")

edit(f"{ROOT}/README.zh-CN.md",
     "sqlseed 通过 SQLAlchemy 支持 SQLite（默认）、PostgreSQL 和 MySQL。",
     "sqlseed 通过 SQLAlchemy 支持 SQLite（默认）和 PostgreSQL。MySQL 支持已移除（待 PostgreSQL 完全验证后再议）。")

edit(f"{ROOT}/README.zh-CN.md",
     "# MySQL 支持（mysqlclient 驱动）\npip install \"sqlseed[mysql]\"",
     "")

edit(f"{ROOT}/README.zh-CN.md",
     "# 所有数据库后端 + 所有数据引擎\npip install \"sqlseed[all]\"",
     "# 所有数据库后端 + 所有数据引擎 + testcontainers\npip install \"sqlseed[all]\"")

edit(f"{ROOT}/README.zh-CN.md",
     "> **💡 提示**：SQLite 开箱即用，无需额外依赖。PostgreSQL/MySQL 驱动仅在连接对应数据库时需要安装。",
     "> **💡 提示**：SQLite 开箱即用，无需额外依赖。PostgreSQL 驱动仅在连接 PostgreSQL 时需要安装。")

edit(f"{ROOT}/README.zh-CN.md",
     "### 连接 PostgreSQL / MySQL",
     "### 连接 PostgreSQL")

edit(f"{ROOT}/README.zh-CN.md",
     "sqlseed 除 SQLite 外，还支持 PostgreSQL 和 MySQL。传入 SQLAlchemy URL 替代文件路径即可：",
     "sqlseed 除 SQLite 外，还支持 PostgreSQL。传入 SQLAlchemy URL 替代文件路径即可：")

edit(f"{ROOT}/README.zh-CN.md",
     "# MySQL（需安装：pip install \"sqlseed[mysql]\"）\nresult = sqlseed.fill(\n    \"mysql+mysqldb://user:password@localhost:3306/mydb\",\n    table=\"users\",\n    count=10_000,\n)\nprint(result)\n```",
     "```")

edit(f"{ROOT}/README.zh-CN.md",
     "三种数据库使用相同的 API —— Schema 推断、外键解析、表达式引擎和插件 Hook 在 SQLite、PostgreSQL 和 MySQL 上行为完全一致。",
     "两种数据库使用相同的 API —— Schema 推断、外键解析、表达式引擎和插件 Hook 在 SQLite 和 PostgreSQL 上行为完全一致。")

edit(f"{ROOT}/README.zh-CN.md",
     "│   ├── sqlalchemy_adapter.py    # 默认适配器（SQLite/PostgreSQL/MySQL）",
     "│   ├── sqlalchemy_adapter.py    # 默认适配器（SQLite/PostgreSQL）")

edit(f"{ROOT}/README.zh-CN.md",
     "├── cli/                     # ===== CLI =====\n│   └── main.py              # click 命令（fill/preview/inspect/init/replay/ai-suggest）",
     "")

edit(f"{ROOT}/README.zh-CN.md",
     "| `sqlseed[mysql]` | + mysqlclient | MySQL SQLAlchemy 驱动 |",
     "")

# ---- docs/architecture.zh-CN.md MCP section ----
edit(f"{ROOT}/docs/architecture.zh-CN.md",
     """## 10. MCP 服务器架构

```mermaid
flowchart LR
    subgraph Client["AI 助手 (Claude/Cursor/...)"]
        Request["MCP 请求"]
    end

    subgraph MCPServer["mcp-server-sqlseed (FastMCP)"]
        Resource["📖 Resource<br/>sqlseed://schema/{db}/{table}"]
        Tool1["🔍 sqlseed_inspect_schema<br/>返回: 列 + FK + 索引 + 样本 + hash"]
        Tool2["🤖 sqlseed_generate_yaml<br/>AI 分析 → 自纠正 → YAML"]
        Tool3["⚡ sqlseed_execute_fill<br/>执行数据生成"]
        Tool4["💎 sqlseed_gemma4_analyze<br/>Gemma 4 原生函数调用分析"]
        Tool5["💎 sqlseed_gemma4_agent_fill<br/>Gemma 4 Agent 驱动数据填充"]
        Tool6["💎 sqlseed_list_gemma_models<br/>列出可用 Gemma 4 模型"]
    end

    subgraph SQLSeed["sqlseed 核心"]
        Orchestrator["DataOrchestrator"]
        SchemaCtx["get_schema_context()"]
    end

    subgraph AIPlugin["sqlseed-ai"]
        SA["SchemaAnalyzer"]
        ACR["AiConfigRefiner"]
    end

    Request --> Resource
    Request --> Tool1
    Request --> Tool2
    Request --> Tool3
    Request --> Tool4
    Request --> Tool5
    Request --> Tool6

    Resource --> SchemaCtx
    Tool1 --> SchemaCtx
    Tool2 --> SA --> ACR
    Tool3 --> Orchestrator
    Tool4 --> SA
    Tool5 --> Orchestrator
    Tool6 --> SA

    SchemaCtx --> Orchestrator
```""",
     """## 10. MCP 服务器架构

当前为双服务器架构：

```mermaid
flowchart LR
    subgraph Client["AI 助手 (Claude/Cursor/...)"]
        Request["MCP 请求"]
    end

    subgraph MCPServer["mcp-server-sqlseed (FastMCP)"]
        Tool1["🤖 sqlseed_generate_yaml<br/>规则驱动 → YAML"]
        Tool2["⚡ sqlseed_execute_fill<br/>执行数据生成"]
    end

    subgraph AIMCPServer["sqlseed-ai[mcp] (FastMCP)"]
        Tool3["🤖 sqlseed_ai_generate_yaml<br/>LLM 驱动 YAML 生成"]
        Tool4["💎 sqlseed_gemma4_analyze<br/>Gemma 4 分析"]
        Tool5["💎 sqlseed_gemma4_agent_fill<br/>端到端 Agent"]
        Tool6["💎 sqlseed_list_gemma_models<br/>模型列表"]
    end

    subgraph SQLSeed["sqlseed 核心"]
        Orchestrator["DataOrchestrator"]
        SchemaCtx["get_schema_context()"]
    end

    subgraph AIPlugin["sqlseed-ai"]
        SA["SchemaAnalyzer"]
        ACR["AiConfigRefiner"]
    end

    Request --> Tool1
    Request --> Tool2
    Request --> Tool3
    Request --> Tool4
    Request --> Tool5
    Request --> Tool6

    Tool1 --> SchemaCtx
    Tool2 --> Orchestrator
    Tool3 --> SA --> ACR
    Tool4 --> SA
    Tool5 --> Orchestrator
    Tool6 --> SA

    SchemaCtx --> Orchestrator
```""")

# ---- src/sqlseed/generators/AGENTS.md ----
edit(f"{ROOT}/src/sqlseed/generators/AGENTS.md",
     "├── base_provider.py     # BaseProvider — 31 generators, lazy deps",
     "├── base_provider.py     # BaseProvider — 31 generators, no optional deps")

# ---- plugins/sqlseed-ai/AGENTS.md ----
edit(f"{ROOT}/plugins/sqlseed-ai/AGENTS.md",
     "├── pyproject.toml        # Separate package: sqlseed>=0.1.0, openai>=1.0, httpx>=0.24.0",
     "├── pyproject.toml        # Separate package: sqlseed>=0.1.0, sqlseed-cli>=0.1.0, openai>=1.0, httpx>=0.24.0; optional mcp>=1.0,<2")

print("All targeted fixes done.")
