"""Final batch: MCP tables dual-server split, remaining --backend examples, guide.md."""
from __future__ import annotations
import sys
sys.path.insert(0, "/workspace")
from _edit_helper import edit

ROOT = "/tmp/wt-multi-db"

# ============================================================
# README.md
# ============================================================
# MCP Capabilities table → dual-server
edit(f"{ROOT}/README.md",
     """**MCP Capabilities**:

| Type | Name | Description |
| :--- | :--- | :---------- |
| 📖 Resource | `sqlseed://schema/{db_path}/{table_name}` | Get table schema as JSON |
| 🔍 Tool | `sqlseed_inspect_schema` | Inspect schema (columns, FK, indexes, samples, schema_hash) |
| 🤖 Tool | `sqlseed_generate_yaml` | AI-driven YAML config generation with self-correction. Supports `api_key`/`base_url`/`model` overrides |
| ⚡ Tool | `sqlseed_execute_fill` | Execute data generation (supports YAML config string, includes `enrich` option) |
| 🧠 Tool | `sqlseed_gemma4_analyze` | Analyze schema using Gemma 4 with Native Function Calling |
| 🧠 Tool | `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow (analyze -> config -> fill) |
| 🧠 Tool | `sqlseed_list_gemma_models` | List available Gemma 4 models and backend status |""",
     """**MCP Capabilities** — dual-server architecture:

`mcp-server-sqlseed` (rule-driven, no LLM):

| Type | Name | Description |
| :--- | :--- | :---------- |
| 🤖 Tool | `sqlseed_generate_yaml` | Rule-driven YAML config generation via `ColumnMapper` (no LLM) |
| ⚡ Tool | `sqlseed_execute_fill` | Execute data generation (supports YAML config string, includes `enrich` option) |

`sqlseed-ai[mcp]` (AI tools, requires `pip install "sqlseed-ai[mcp]"`):

| Type | Name | Description |
| :--- | :--- | :---------- |
| 🤖 Tool | `sqlseed_ai_generate_yaml` | AI-driven YAML config generation with self-correction |
| 🧠 Tool | `sqlseed_gemma4_analyze` | Analyze schema using Gemma 4 with Native Function Calling |
| 🧠 Tool | `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow (analyze -> config -> fill) |
| 🧠 Tool | `sqlseed_list_gemma_models` | List available Gemma 4 models and backend status |""")

edit(f"{ROOT}/README.md",
     "The AI assistant will call `sqlseed_inspect_schema` → `sqlseed_generate_yaml` → `sqlseed_execute_fill` in sequence, without you writing any code.",
     "The AI assistant will call `sqlseed_generate_yaml` → `sqlseed_execute_fill` in sequence, without you writing any code.")

# Plugins tree: add sqlseed-cli, fix mcp tools list
edit(f"{ROOT}/README.md",
     """plugins/
├── sqlseed-ai/              # AI plugin — LLM-driven smart configuration
│   └── src/sqlseed_ai/      # SchemaAnalyzer, AiConfigRefiner, few-shot examples...
└── mcp-server-sqlseed/      # MCP server — AI assistant integration
    └── src/mcp_server_sqlseed/   # FastMCP tools (sqlseed_inspect_schema/sqlseed_generate_yaml/sqlseed_execute_fill)""",
     """plugins/
├── sqlseed-cli/             # CLI plugin — the `sqlseed` console command
│   └── src/sqlseed_cli/     # fill / preview / inspect / init / replay subcommands
├── sqlseed-ai/              # AI plugin — LLM-driven smart configuration
│   └── src/sqlseed_ai/      # SchemaAnalyzer, AiConfigRefiner, MCP AI tools, ai-suggest CLI...
└── mcp-server-sqlseed/      # MCP server — AI assistant integration (no LLM)
    └── src/mcp_server_sqlseed/   # FastMCP tools (sqlseed_generate_yaml/sqlseed_execute_fill)""")

# ============================================================
# README.zh-CN.md
# ============================================================
# 4 ai-suggest examples with --backend
edit(f"{ROOT}/README.zh-CN.md",
     """# 指定模型（支持多后端：Google AI Studio、LM Studio、Ollama、OpenAI-compatible）
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-26b-a4b-it --backend google_ai_studio
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-31b-it --backend google_ai_studio
sqlseed ai-suggest app.db --table projects -o projects.yaml --model google/gemma-4-e4b --backend lm_studio
sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-e4b-it --backend ollama""",
     """# 指定模型（支持多后端：Google AI Studio、LM Studio、Ollama、OpenAI-compatible）
SQLSEED_AI_BACKEND=google_ai_studio sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-26b-a4b-it
SQLSEED_AI_BACKEND=google_ai_studio sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-31b-it
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table projects -o projects.yaml --model google/gemma-4-e4b
SQLSEED_AI_BACKEND=ollama sqlseed ai-suggest app.db --table projects -o projects.yaml --model gemma-4-e4b-it""")

# MCP 提供的能力 table → dual-server
edit(f"{ROOT}/README.zh-CN.md",
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
     """**MCP 提供的能力** —— 双服务器架构：

`mcp-server-sqlseed`（规则驱动，无 LLM 依赖）：

| 类型 | 名称 | 说明 |
| :--- | :--- | :--- |
| 🤖 Tool | `sqlseed_generate_yaml` | 规则驱动的 YAML 配置生成（基于 `ColumnMapper`，无 LLM） |
| ⚡ Tool | `sqlseed_execute_fill` | 执行数据生成（支持 YAML 配置字符串，含 `enrich` 选项） |

`sqlseed-ai[mcp]`（AI 工具，需 `pip install "sqlseed-ai[mcp]"`）：

| 类型 | 名称 | 说明 |
| :--- | :--- | :--- |
| 🤖 Tool | `sqlseed_ai_generate_yaml` | AI 驱动的 YAML 配置生成（含自纠正） |
| 🤖 Tool | `sqlseed_gemma4_analyze` | Gemma 4 原生函数调用分析 Schema（GEMMA_TOOLS 协议） |
| 🤖 Tool | `sqlseed_gemma4_agent_fill` | Gemma 4 Agent 模式端到端数据生成（分析→配置→填充） |
| 📋 Tool | `sqlseed_list_gemma_models` | 列出可用的 Gemma 4 模型及后端支持情况 |""")

# AI 后端选择 block: remaining 3 --backend lines
edit(f"{ROOT}/README.zh-CN.md",
     "sqlseed ai-suggest app.db -t users -o users.yaml --backend google_ai_studio --model gemma-4-26b-a4b-it",
     "SQLSEED_AI_BACKEND=google_ai_studio sqlseed ai-suggest app.db -t users -o users.yaml --model gemma-4-26b-a4b-it")
edit(f"{ROOT}/README.zh-CN.md",
     "sqlseed ai-suggest app.db -t users -o users.yaml --backend ollama --model gemma-4-e4b-it",
     "SQLSEED_AI_BACKEND=ollama sqlseed ai-suggest app.db -t users -o users.yaml --model gemma-4-e4b-it")
edit(f"{ROOT}/README.zh-CN.md",
     "sqlseed ai-suggest app.db -t users -o users.yaml --backend openai_compat --model your-model --base-url https://your-api-endpoint",
     "SQLSEED_AI_BACKEND=openai_compat SQLSEED_AI_BASE_URL=https://your-api-endpoint sqlseed ai-suggest app.db -t users -o users.yaml --model your-model")

# ============================================================
# docs/guide.md
# ============================================================
edit(f"{ROOT}/docs/guide.md",
     """# MCP server + AI support (all-in-one)
pip install mcp-server-sqlseed[ai]""",
     """# AI MCP server (Gemma 4 tools, all-in-one)
pip install "sqlseed-ai[mcp]\"""")

edit(f"{ROOT}/docs/guide.md",
     """# Use local LM Studio / Ollama
sqlseed ai-suggest app.db --table projects --output projects.yaml \\
    --backend lm_studio --model google/gemma-4-e4b""",
     """# Use local LM Studio / Ollama (backend via env var)
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table projects --output projects.yaml \\
    --model google/gemma-4-e4b""")

edit(f"{ROOT}/docs/guide.md",
     """# All-in-one: MCP server + AI support
pip install mcp-server-sqlseed[ai]""",
     """# AI MCP server (Gemma 4 tools)
pip install "sqlseed-ai[mcp]\"""")

edit(f"{ROOT}/docs/guide.md",
     """| Type | Name | Description |
|------|------|-------------|
| 📖 Resource | `sqlseed://schema/{db_path}/{table_name}` | Get table schema as JSON |
| 🔍 Tool | `sqlseed_inspect_schema` | Inspect schema (columns, FK, indexes, samples, schema_hash) |
| 🤖 Tool | `sqlseed_generate_yaml` | AI-driven YAML config generation with self-correction |
| ⚡ Tool | `sqlseed_execute_fill` | Execute data generation (supports YAML config string, includes `enrich`) |
| 🧠 Tool | `sqlseed_gemma4_analyze` | Analyze schema using Gemma 4 with Native Function Calling |
| 🧠 Tool | `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow (analyze → config → fill) |
| 🧠 Tool | `sqlseed_list_gemma_models` | List available Gemma 4 models and backend status |""",
     """`mcp-server-sqlseed` (rule-driven, no LLM):

| Type | Name | Description |
|------|------|-------------|
| 🤖 Tool | `sqlseed_generate_yaml` | Rule-driven YAML config generation via `ColumnMapper` (no LLM) |
| ⚡ Tool | `sqlseed_execute_fill` | Execute data generation (supports YAML config string, includes `enrich`) |

`sqlseed-ai[mcp]` (AI tools):

| Type | Name | Description |
|------|------|-------------|
| 🤖 Tool | `sqlseed_ai_generate_yaml` | AI-driven YAML config generation with self-correction |
| 🧠 Tool | `sqlseed_gemma4_analyze` | Analyze schema using Gemma 4 with Native Function Calling |
| 🧠 Tool | `sqlseed_gemma4_agent_fill` | End-to-end Agent workflow (analyze → config → fill) |
| 🧠 Tool | `sqlseed_list_gemma_models` | List available Gemma 4 models and backend status |""")

edit(f"{ROOT}/docs/guide.md",
     """The AI assistant will call `sqlseed_inspect_schema` →
`sqlseed_generate_yaml` → `sqlseed_execute_fill` in sequence, without you
writing any code.""",
     """The AI assistant will call `sqlseed_generate_yaml` →
`sqlseed_execute_fill` in sequence, without you
writing any code.""")

print("Final batch done.")
