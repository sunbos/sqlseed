"""Fix README.zh-CN.md: MySQL removal, --backend removal, MCP split, tree sync, deps table."""
from pathlib import Path

p = Path("/tmp/wt-contract/README.zh-CN.md")
text = p.read_text(encoding="utf-8")
orig = text
n0 = len(text)

# ── 1. Data engine section: sqlseed[faker] extra does not exist (faker is core dep) ──
text = text.replace(
    """# 可选：Faker（生态丰富）
pip install sqlseed[faker]""",
    """# 注意：Faker 是必需的核心依赖，已包含在 `pip install sqlseed` 中""",
)

# ── 2. Database backend section: drop MySQL ──
text = text.replace(
    "sqlseed 通过 SQLAlchemy 支持 SQLite（默认）、PostgreSQL 和 MySQL。",
    "sqlseed 通过 SQLAlchemy 支持 SQLite（默认）和 PostgreSQL。",
)
text = text.replace(
    """# PostgreSQL 支持（psycopg 驱动）
pip install "sqlseed[postgres]"

# MySQL 支持（mysqlclient 驱动）
pip install "sqlseed[mysql]"

# 所有数据库后端 + 所有数据引擎
pip install "sqlseed[all]\"""",
    """# PostgreSQL 支持（psycopg 驱动）
pip install "sqlseed[postgres]"

# 所有数据库后端 + 所有数据引擎
pip install "sqlseed[all]\"""",
)
text = text.replace(
    "> **💡 提示**：SQLite 开箱即用，无需额外依赖。PostgreSQL/MySQL 驱动仅在连接对应数据库时需要安装。",
    "> **💡 提示**：SQLite 开箱即用，无需额外依赖。PostgreSQL 驱动仅在连接对应数据库时需要安装。",
)

# ── 3. Optional plugins install: add sqlseed-cli; fix mcp-server-sqlseed[ai] ──
text = text.replace(
    """```bash
# AI 智能分析插件（依赖 openai SDK）
pip install sqlseed-ai

# MCP 服务器（依赖 mcp SDK，让 AI 助手直接操作 sqlseed）
pip install mcp-server-sqlseed

# MCP 服务器 + AI 支持（一步到位）
pip install mcp-server-sqlseed[ai]
```""",
    """```bash
# CLI 插件（提供 `sqlseed` 命令；自动拉取 sqlseed 核心）
pip install sqlseed-cli

# AI 智能分析插件（依赖 openai SDK）
pip install sqlseed-ai

# MCP 服务器（依赖 mcp SDK，让 AI 助手直接操作 sqlseed）
pip install mcp-server-sqlseed

# AI MCP 服务器（4 个 LLM 工具，依赖 sqlseed-ai）
pip install "sqlseed-ai[mcp]"
```""",
)

# ── 4. PostgreSQL / MySQL connect section ──
text = text.replace(
    "### 连接 PostgreSQL / MySQL",
    "### 连接 PostgreSQL",
)
text = text.replace(
    "sqlseed 除 SQLite 外，还支持 PostgreSQL 和 MySQL。传入 SQLAlchemy URL 替代文件路径即可：",
    "sqlseed 除 SQLite 外还支持 PostgreSQL。传入 SQLAlchemy URL 替代文件路径即可：",
)
text = text.replace(
    """print(result)

# MySQL（需安装：pip install "sqlseed[mysql]"）
result = sqlseed.fill(
    "mysql+mysqldb://user:password@localhost:3306/mydb",
    table="users",
    count=10_000,
)
print(result)
```

三种数据库使用相同的 API —— Schema 推断、外键解析、表达式引擎和插件 Hook 在 SQLite、PostgreSQL 和 MySQL 上行为完全一致。""",
    """print(result)
```

两种数据库使用相同的 API —— Schema 推断、外键解析、表达式引擎和插件 Hook 在 SQLite 和 PostgreSQL 上行为完全一致。""",
)

# ── 5. ai-suggest --backend examples -> env var ──
text = text.replace(
    """# 指定模型（支持多后端：Google AI Studio、LM Studio、Ollama、OpenAI-compatible）
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-26b-a4b-it --backend google_ai_studio
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-31b-it --backend google_ai_studio
sqlseed ai-suggest app.db --table projects -o projects.yaml --model google/gemma-4-e4b --backend lm_studio
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-e4b-it --backend ollama""",
    """# 指定模型（后端通过 SQLSEED_AI_BACKEND 环境变量选择，无 --backend 选项）
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-26b-a4b-it
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-31b-it
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table projects -o projects.yaml --model google/gemma-4-e4b
SQLSEED_AI_BACKEND=ollama sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma4:e4b""",
)

# ── 6. Backend table: drop --backend ──
text = text.replace(
    "| **Google AI Studio** | 官方 API，推荐 Gemma 4 26B/31B | `--backend google_ai_studio` 或 `SQLSEED_AI_BACKEND=google_ai_studio` |",
    "| **Google AI Studio** | 官方 API，推荐 Gemma 4 26B/31B | `SQLSEED_AI_BACKEND=google_ai_studio` |",
)
text = text.replace(
    "| **LM Studio** | 本地推理，适合 Gemma 4 2B/4B | `--backend lm_studio` 或 `SQLSEED_AI_BACKEND=lm_studio` |",
    "| **LM Studio** | 本地推理，适合 Gemma 4 2B/4B | `SQLSEED_AI_BACKEND=lm_studio`（默认 URL `http://127.0.0.1:1234/v1`） |",
)
text = text.replace(
    "| **Ollama** | 本地推理，适合 Gemma 4 2B/4B/26B | `--backend ollama` 或 `SQLSEED_AI_BACKEND=ollama` |",
    "| **Ollama** | 本地推理，适合 Gemma 4 2B/4B/26B | `SQLSEED_AI_BACKEND=ollama` |",
)
text = text.replace(
    "| **OpenAI-compatible** | 通用 OpenAI 兼容端点（如 OpenRouter、DeepSeek） | `--backend openai_compat` 或 `SQLSEED_AI_BACKEND=openai_compat` |",
    "| **OpenAI-compatible** | 通用 OpenAI 兼容端点（如 OpenRouter、DeepSeek） | `SQLSEED_AI_BACKEND=openai_compat` |",
)

# ── 7. Tutorial 9: MCP install + capabilities split (core 2 tools / AI 4 tools) ──
text = text.replace(
    """```bash
pip install mcp-server-sqlseed[ai]

# 配置 Claude Desktop
```""",
    """```bash
# 安装核心 MCP 服务器（无 LLM 依赖）
pip install mcp-server-sqlseed

# 安装 AI MCP 服务器（LLM 驱动，依赖 sqlseed-ai）
pip install "sqlseed-ai[mcp]"

# 配置 Claude Desktop
```""",
)
text = text.replace(
    """**MCP 提供的能力**：

| 类型 | 名称 | 说明 |
| :--- | :--- | :--- |
| 📖 Resource | `sqlseed://schema/{db_path}/{table_name}` | 获取表 Schema 的 JSON 表示 |
| 🔍 Tool | `sqlseed_inspect_schema` | 检查 Schema（列、外键、索引、样本数据、schema_hash） |
| 🤖 Tool | `sqlseed_generate_yaml` | AI 驱动的 YAML 配置生成（含自纠正） |
| ⚡ Tool | `sqlseed_execute_fill` | 执行数据生成（支持 YAML 配置字符串，含 `enrich` 选项） |
| 🤖 Tool | `sqlseed_gemma4_analyze` | Gemma 4 原生函数调用分析 Schema（GEMMA_TOOLS 协议） |
| 🤖 Tool | `sqlseed_gemma4_agent_fill` | Gemma 4 Agent 模式端到端数据生成（分析→配置→填充） |
| 📋 Tool | `sqlseed_list_gemma_models` | 列出可用的 Gemma 4 模型及后端支持情况 |""",
    """**MCP 提供的能力**：

**mcp-server-sqlseed**（2 个工具，0 个资源 —— 核心，无 LLM 依赖）：

| 类型 | 名称 | 说明 |
| :--- | :--- | :--- |
| 🤖 Tool | `sqlseed_generate_yaml` | 规则驱动的 YAML 配置生成（经由 `ColumnMapper`） |
| ⚡ Tool | `sqlseed_execute_fill` | 执行数据生成（支持 YAML 配置字符串，含 `enrich` 选项） |

**sqlseed-ai[mcp]**（4 个工具，0 个资源 —— LLM 驱动，通过 `pip install "sqlseed-ai[mcp]"` 安装）：

| 类型 | 名称 | 说明 |
| :--- | :--- | :--- |
| 🧠 Tool | `sqlseed_ai_generate_yaml` | AI 驱动的 YAML 配置生成（含自纠正） |
| 🧠 Tool | `sqlseed_gemma4_analyze` | Gemma 4 原生函数调用分析 Schema（GEMMA_TOOLS 协议） |
| 🧠 Tool | `sqlseed_gemma4_agent_fill` | Gemma 4 Agent 模式端到端数据生成（分析→配置→填充） |
| 🧠 Tool | `sqlseed_list_gemma_models` | 列出可用的 Gemma 4 模型及后端支持情况 |""",
)

# ── 8. CLI reference: replace --backend block with env var examples ──
text = text.replace(
    """# ═══ AI 后端选择 ═══
sqlseed ai-suggest app.db -t users -o users.yaml --backend google_ai_studio --model gemma-4-26b-a4b-it
sqlseed ai-suggest app.db -t users -o users.yaml --backend ollama --model gemma-4-e4b-it
sqlseed ai-suggest app.db -t users -o users.yaml --backend lm_studio --model google/gemma-4-e4b
sqlseed ai-suggest app.db -t users -o users.yaml --backend openai_compat --model your-model --base-url https://your-api-endpoint""",
    """# ═══ AI 后端选择（通过环境变量，无 --backend 选项）═══
SQLSEED_AI_BACKEND=google_ai_studio sqlseed ai-suggest app.db -t users -o users.yaml --model gemma-4-26b-a4b-it
SQLSEED_AI_BACKEND=ollama sqlseed ai-suggest app.db -t users -o users.yaml --model gemma4:e4b
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db -t users -o users.yaml --model google/gemma-4-e4b
SQLSEED_AI_BACKEND=openai_compat sqlseed ai-suggest app.db -t users -o users.yaml --model your-model --base-url https://your-api-endpoint""",
)

# ── 9. Architecture tree: sync with source (orchestrator pkg, no cli/, no MySQL, +sqlseed-cli) ──
text = text.replace(
    """├── core/                    # ===== 核心编排层 =====
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
│   └── stream.py            # DataStream 流式生成 + 约束回溯
├── database/                # ===== 数据库层 =====
│   ├── _protocol.py         # DatabaseAdapter Protocol (ColumnInfo, ForeignKeyInfo, IndexInfo)
│   ├── sqlalchemy_adapter.py    # 默认适配器（SQLite/PostgreSQL/MySQL）
│   ├── raw_sqlite_adapter.py     # sqlite3 回退适配器
│   └── optimizer.py         # PragmaOptimizer 三级优化
├── plugins/                 # ===== 插件层 =====
│   ├── hookspecs.py         # 12 个 pluggy Hook 定义
│   └── manager.py           # PluginManager
├── config/                  # ===== 配置管理 =====
│   ├── models.py            # Pydantic 模型 (GeneratorConfig/TableConfig/ColumnConfig)
│   ├── loader.py            # YAML/JSON 加载与保存
│   └── snapshot.py          # 快照保存与加载
├── cli/                     # ===== CLI =====
│   └── main.py              # click 命令 (fill/preview/inspect/init/replay)
└── _utils/                  # ===== 内部工具 =====""",
    """├── core/                    # ===== 核心编排层 =====
│   ├── orchestrator/        # DataOrchestrator 包（4 个 mixin + 1 个共享数据模块）
│   │   ├── __init__.py
│   │   ├── _common.py
│   │   ├── _connection.py
│   │   ├── _specs.py
│   │   ├── _generation.py
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
│   ├── registry.py          # ProviderRegistry (entry-point 自动发现)
│   ├── base_provider.py     # 内置基础生成器（零依赖）
│   ├── faker_provider.py    # Faker 适配器
│   └── mimesis_provider.py  # Mimesis 适配器
├── database/                # ===== 数据库层 =====
│   ├── _protocol.py         # DatabaseAdapter Protocol (ColumnInfo, ForeignKeyInfo, IndexInfo)
│   ├── sqlalchemy_adapter.py    # 默认适配器（SQLite/PostgreSQL）
│   ├── raw_sqlite_adapter.py     # sqlite3 回退适配器
│   └── optimizer.py         # PragmaOptimizer 三级优化
├── plugins/                 # ===== 插件层 =====
│   ├── hookspecs.py         # 12 个 pluggy Hook 定义
│   └── manager.py           # PluginManager
├── config/                  # ===== 配置管理 =====
│   ├── models.py            # Pydantic 模型 (GeneratorConfig/TableConfig/ColumnConfig)
│   ├── loader.py            # YAML/JSON 加载与保存
│   └── snapshot.py          # 快照保存与加载
└── _utils/                  # ===== 内部工具 =====""",
)
text = text.replace(
    """plugins/
├── sqlseed-ai/              # AI 插件 — LLM 驱动的智能配置
│   └── src/sqlseed_ai/      # SchemaAnalyzer, AiConfigRefiner, Few-shot 示例...
└── mcp-server-sqlseed/      # MCP 服务器 — AI 助手交互
    └── src/mcp_server_sqlseed/   # FastMCP 工具
```""",
    """plugins/
├── sqlseed-cli/             # CLI 插件 — click 命令 (fill/preview/inspect/init/replay)
│   └── src/sqlseed_cli/     # 独立包，单独 pyproject.toml
├── sqlseed-ai/              # AI 插件 — LLM 驱动的智能配置
│   └── src/sqlseed_ai/      # SchemaAnalyzer, AiConfigRefiner, Few-shot 示例...
└── mcp-server-sqlseed/      # MCP 服务器 — AI 助手交互
    └── src/mcp_server_sqlseed/   # FastMCP 工具 (sqlseed_generate_yaml/sqlseed_execute_fill)
```""",
)

# ── 10. Dependencies table ──
text = text.replace(
    """| `sqlseed` | sqlalchemy, pydantic, pluggy, structlog, pyyaml, click, rich, typing_extensions, simpleeval, **rstr** | rstr 用于 `pattern` 生成器的正则匹配 |
| `sqlseed[faker]` | + faker>=30.0 | Faker 数据引擎 |
| `sqlseed[mimesis]` | + mimesis>=18.0 | Mimesis 数据引擎（推荐） |
| `sqlseed[postgres]` | + psycopg | PostgreSQL SQLAlchemy 驱动 |
| `sqlseed[mysql]` | + mysqlclient | MySQL SQLAlchemy 驱动 |
| `sqlseed[docs]` | + mkdocs-material, mkdocstrings | 文档构建 |
| `sqlseed-ai` | sqlseed, **openai>=1.0** | AI 插件，通过 entry-point 自动注册，支持 Gemma 4 GEMMA_TOOLS |
| `mcp-server-sqlseed` | sqlseed, **mcp>=1.0** | MCP 服务器，独立 CLI 工具 |
| `mcp-server-sqlseed[ai]` | + sqlseed-ai | MCP 服务器含 AI 支持 |""",
    """| `sqlseed` | sqlalchemy, pydantic, pluggy, structlog, pyyaml, faker, typing_extensions, simpleeval, **rstr** | faker 为必需核心依赖；rstr 用于 `pattern` 生成器的正则匹配 |
| `sqlseed[mimesis]` | + mimesis>=18.0 | Mimesis 数据引擎（推荐） |
| `sqlseed[postgres]` | + psycopg | PostgreSQL SQLAlchemy 驱动 |
| `sqlseed[docs]` | + mkdocs-material, mkdocstrings | 文档构建 |
| `sqlseed-cli` | sqlseed, **click**, **rich** | CLI 插件 —— 提供 `sqlseed` 命令 (fill/preview/inspect/init/replay)，自动拉取 sqlseed 核心 |
| `sqlseed-ai` | sqlseed, **openai>=1.0** | AI 插件（Gemma 4 原生函数调用），通过 entry-point 自动注册 |
| `sqlseed-ai[mcp]` | + sqlseed-ai, **mcp>=1.0** | AI MCP 服务器（4 个 LLM 工具）；通过 `pip install "sqlseed-ai[mcp]"` 安装 |
| `mcp-server-sqlseed` | sqlseed, **mcp>=1.0** | MCP 服务器（2 个核心工具，无 LLM），独立 CLI 工具 |""",
)

if text == orig:
    raise SystemExit("NO CHANGES MADE — check patterns")
p.write_text(text, encoding="utf-8")
print(f"README.zh-CN.md updated ({n0} -> {len(text)} chars)")
