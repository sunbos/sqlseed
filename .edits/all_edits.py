"""Batch edits for docs sync in /tmp/wt-multi-db."""
from __future__ import annotations

import sys
sys.path.insert(0, "/workspace")
from _edit_helper import edit

ROOT = "/tmp/wt-multi-db"

# =====================================================================
# 1. Root AGENTS.md (already partially done externally; keep in sync)
# =====================================================================
# Header already updated.

# =====================================================================
# 2. README.md
# =====================================================================
# --backend lm_studio → env var
edit(f"{ROOT}/README.md",
     "sqlseed ai-suggest app.db --table projects --output projects.yaml --backend lm_studio --model google/gemma-4-e4b",
     "SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table projects --output projects.yaml --model google/gemma-4-e4b")

# Backend table: remove --backend column, add "(default)" to google_ai_studio
edit(f"{ROOT}/README.md",
     """| Backend | Description | Configuration |
| :------ | :---------- | :------------ |
| **Google AI Studio** | Official API, recommended for Gemma 4 26B/31B | `--backend google_ai_studio` or `SQLSEED_AI_BACKEND=google_ai_studio` |
| **LM Studio** | Local inference, suitable for Gemma 4 2B/4B | `--backend lm_studio` or `SQLSEED_AI_BACKEND=lm_studio` |
| **Ollama** | Local inference, suitable for Gemma 4 2B/4B/26B | `--backend ollama` or `SQLSEED_AI_BACKEND=ollama` |
| **OpenAI-compatible** | Generic OpenAI-compatible endpoint (e.g., OpenRouter, DeepSeek) | `--backend openai_compat` or `SQLSEED_AI_BACKEND=openai_compat` |""",
     """| Backend | Description |
| :------ | :---------- |
| **Google AI Studio** | Official API, recommended for Gemma 4 26B/31B (default) |
| **LM Studio** | Local inference, suitable for Gemma 4 2B/4B |
| **Ollama** | Local inference, suitable for Gemma 4 2B/4B/26B |
| **OpenAI-compatible** | Generic OpenAI-compatible endpoint (e.g., OpenRouter, DeepSeek) |

Set backend via `SQLSEED_AI_BACKEND` environment variable.""")

# sqlseed[all] extras: add testcontainers
edit(f"{ROOT}/README.md",
     "| `sqlseed[all]` | All data engines + all DB drivers (faker, mimesis, psycopg) + tqdm |",
     "| `sqlseed[all]` | All data engines + all DB drivers (faker, mimesis, psycopg, testcontainers) + tqdm |")

# sqlseed[all] line in deps table
edit(f"{ROOT}/README.md",
     "| `sqlseed[all]` | `mimesis>=18.0`, `tqdm>=4.66`, `psycopg[binary]>=3.0`, `sqlseed-cli>=0.1.0` | All data engines + all DB drivers + tqdm + CLI |",
     "| `sqlseed[all]` | `mimesis>=18.0`, `tqdm>=4.66`, `psycopg[binary]>=3.0`, `testcontainers>=4.0`, `sqlseed-cli>=0.1.0` | All data engines + all DB drivers + tqdm + CLI + testcontainers |")

# generators architecture tree in README: add _json_helpers.py, _string_helpers.py
edit(f"{ROOT}/README.md",
     "│   ├── base_provider.py     # Built-in base generators (zero dependencies)\n│   ├── faker_provider.py    # Faker adapter\n│   ├── mimesis_provider.py  # Mimesis adapter\n│   └── stream.py            # DataStream streaming + constraint backtracking",
     "│   ├── base_provider.py     # Built-in base generators (zero dependencies)\n│   ├── faker_provider.py    # Faker adapter\n│   ├── mimesis_provider.py  # Mimesis adapter\n│   ├── _json_helpers.py     # JSON schema-based generation helpers\n│   ├── _string_helpers.py   # Random string utilities\n│   └── stream.py            # DataStream streaming + constraint backtracking")

# =====================================================================
# 3. README.zh-CN.md
# =====================================================================
# --backend lm_studio → env var (Chinese section)
edit(f"{ROOT}/README.zh-CN.md",
     "sqlseed ai-suggest app.db -t users -o users.yaml --backend lm_studio --model google/gemma-4-e4b",
     "SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db -t users -o users.yaml --model google/gemma-4-e4b")

# Backend table Chinese
edit(f"{ROOT}/README.zh-CN.md",
     """| 后端 | 说明 | 配置方式 |
| :--- | :--- | :--- |
| **Google AI Studio** | 官方 API，推荐 Gemma 4 26B/31B | `--backend google_ai_studio` 或 `SQLSEED_AI_BACKEND=google_ai_studio` |
| **LM Studio** | 本地推理，适合 Gemma 4 2B/4B | `--backend lm_studio` 或 `SQLSEED_AI_BACKEND=lm_studio` |
| **Ollama** | 本地推理，适合 Gemma 4 2B/4B/26B | `--backend ollama` 或 `SQLSEED_AI_BACKEND=ollama` |
| **OpenAI-compatible** | 通用 OpenAI 兼容端点（如 OpenRouter、DeepSeek） | `--backend openai_compat` 或 `SQLSEED_AI_BACKEND=openai_compat` |""",
     """| 后端 | 说明 |
| :--- | :--- |
| **Google AI Studio** | 官方 API，推荐 Gemma 4 26B/31B（默认） |
| **LM Studio** | 本地推理，适合 Gemma 4 2B/4B |
| **Ollama** | 本地推理，适合 Gemma 4 2B/4B/26B |
| **OpenAI-compatible** | 通用 OpenAI 兼容端点（如 OpenRouter、DeepSeek） |

通过后端的 `SQLSEED_AI_BACKEND` 环境变量设置。""")

# sqlseed[all] extras Chinese
edit(f"{ROOT}/README.zh-CN.md",
     "| `sqlseed[all]` | `mimesis>=18.0`，`tqdm>=4.66`，`psycopg[binary]>=3.0`，`sqlseed-cli>=0.1.0` | 所有数据引擎 + 所有数据库驱动 + tqdm + CLI |",
     "| `sqlseed[all]` | `mimesis>=18.0`，`tqdm>=4.66`，`psycopg[binary]>=3.0`，`testcontainers>=4.0`，`sqlseed-cli>=0.1.0` | 所有数据引擎 + 所有数据库驱动 + tqdm + CLI + testcontainers |")

# generators architecture tree Chinese
edit(f"{ROOT}/README.zh-CN.md",
     "│   ├── base_provider.py     # 内置基础生成器（零依赖）\n│   ├── faker_provider.py    # Faker 适配器\n│   ├── mimesis_provider.py  # Mimesis 适配器\n│   └── stream.py            # DataStream 流式生成 + 约束回溯",
     "│   ├── base_provider.py     # 内置基础生成器（零依赖）\n│   ├── faker_provider.py    # Faker 适配器\n│   ├── mimesis_provider.py  # Mimesis 适配器\n│   ├── _json_helpers.py     # JSON schema 生成辅助\n│   ├── _string_helpers.py   # 随机字符串工具\n│   └── stream.py            # DataStream 流式生成 + 约束回溯")

# AI backend quick-ref block in README.zh-CN.md
edit(f"{ROOT}/README.zh-CN.md",
     """# ═══ AI 后端选择 ═══
sqlseed ai-suggest app.db -t users -o users.yaml --backend google_ai_studio --model gemma-4-26b-a4b-it
sqlseed ai-suggest app.db -t users -o users.yaml --backend ollama --model gemma-4-e4b-it
sqlseed ai-suggest app.db -t users -o users.yaml --backend lm_studio --model google/gemma-4-e4b
sqlseed ai-suggest app.db -t users -o users.yaml --backend openai_compat --model your-model --base-url https://your-api-endpoint""",
     """# ═══ AI 后端选择 ═══
SQLSEED_AI_BACKEND=google_ai_studio sqlseed ai-suggest app.db -t users -o users.yaml --model gemma-4-26b-a4b-it
SQLSEED_AI_BACKEND=ollama sqlseed ai-suggest app.db -t users -o users.yaml --model gemma-4-e4b-it
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db -t users -o users.yaml --model google/gemma-4-e4b
SQLSEED_AI_BACKEND=openai_compat SQLSEED_AI_BASE_URL=https://your-api-endpoint sqlseed ai-suggest app.db -t users -o users.yaml --model your-model""")

# =====================================================================
# 4. docs/guide.md
# =====================================================================
# Remove --backend row, add --timeout row, remove "via --backend" text
edit(f"{ROOT}/docs/guide.md",
     "sqlseed-ai supports multiple backends for Gemma 4 models. Set the backend via\n`--backend` or the `SQLSEED_AI_BACKEND` environment variable.",
     "sqlseed-ai supports multiple backends for Gemma 4 models. Set the backend via\nthe `SQLSEED_AI_BACKEND` environment variable.")

edit(f"{ROOT}/docs/guide.md",
     """| `--model` | Model name (default: Gemma 4 26B) |
| `--backend` | `google_ai_studio` / `lm_studio` / `ollama` / `openai_compat` |""",
     """| `--model` | Model name (default: Gemma 4 26B) |
| `--timeout` | API timeout in seconds (default: auto-resolve per backend) |

> **Note**: Backend selection is done via the `SQLSEED_AI_BACKEND` environment\n> variable, not via a CLI option.""")

# Add testcontainers to sqlseed[all] in guide.md
edit(f"{ROOT}/docs/guide.md",
     "# Install all data engines + all database drivers + tqdm\npip install sqlseed[all]",
     "# Install all data engines + all database drivers + tqdm + testcontainers\npip install sqlseed[all]")

# =====================================================================
# 5. docs/index.md
# =====================================================================
edit(f"{ROOT}/docs/index.md",
     "| `pip install sqlseed[all]` | All data engines + all DB drivers (faker, mimesis, psycopg) + tqdm |",
     "| `pip install sqlseed[all]` | All data engines + all DB drivers (faker, mimesis, psycopg, testcontainers) + tqdm |")

# =====================================================================
# 6. docs/architecture.zh-CN.md
# =====================================================================
# §7: sqlseed_generate_yaml → sqlseed_ai_generate_yaml
edit(f"{ROOT}/docs/architecture.zh-CN.md",
     "        MCPTool[\"MCP: sqlseed_generate_yaml\"]",
     "        MCPTool[\"MCP: sqlseed_ai_generate_yaml\"]")

# §10 MCP architecture rewrite (Chinese)
edit(f"{ROOT}/docs/architecture.zh-CN.md",
     """## 10. MCP 服务器架构

```mermaid
flowchart LR
    subgraph Client["AI 助手 (Claude/Cursor/...)"]
        Request["MCP 请求"]
    end

    subgraph MCPServer["mcp-server-sqlseed (FastMCP)"]
        Resource["📖 Resource\nsqlseed://schema/{db}/{table}"]
        Tool1["🔍 sqlseed_inspect_schema\n返回: 列 + FK + 索引 + 样本 + hash"]
        Tool2["🤖 sqlseed_generate_yaml\nAI 分析 → 自纠正 → YAML"]
        Tool3["⚡ sqlseed_execute_fill\n执行数据生成"]
        Tool4["💎 sqlseed_gemma4_analyze\nGemma 4 原生函数调用分析"]
        Tool5["💎 sqlseed_gemma4_agent_fill\nGemma 4 Agent 驱动数据填充"]
        Tool6["💎 sqlseed_list_gemma_models\n列出可用 Gemma 4 模型"]
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
        Tool1["🤖 sqlseed_generate_yaml\n规则驱动 → YAML"]
        Tool2["⚡ sqlseed_execute_fill\n执行数据生成"]
    end

    subgraph AIMCPServer["sqlseed-ai[mcp] (FastMCP)"]
        Tool3["🤖 sqlseed_ai_generate_yaml\nLLM 驱动 YAML 生成"]
        Tool4["💎 sqlseed_gemma4_analyze\nGemma 4 分析"]
        Tool5["💎 sqlseed_gemma4_agent_fill\n端到端 Agent"]
        Tool6["💎 sqlseed_list_gemma_models\n模型列表"]
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

# =====================================================================
# 7. CONTRIBUTING.md
# =====================================================================
edit(f"{ROOT}/CONTRIBUTING.md",
     "```bash\n   pip install -e \".[dev,all]\"\n   pip install -e \"./plugins/sqlseed-ai\"\n   pip install -e \"./plugins/mcp-server-sqlseed\"\n   ```",
     "```bash\n   pip install -e \".[dev,all]\"\n   pip install -e \"./plugins/sqlseed-cli\"\n   pip install -e \"./plugins/sqlseed-ai\"\n   pip install -e \"./plugins/mcp-server-sqlseed\"\n   ```")

edit(f"{ROOT}/CONTRIBUTING.md",
     """feat(database): add MySQL support via SQLAlchemyAdapter

- Add pymysql as optional dependency
- Update TypeNormalizer for MySQL types
- Add integration tests for MySQL""",
     """feat(database): add PostgreSQL support via SQLAlchemyAdapter

- Add psycopg as optional dependency
- Update TypeNormalizer for PostgreSQL types
- Add integration tests for PostgreSQL""")

# =====================================================================
# 8. src/sqlseed/AGENTS.md
# =====================================================================
# Delete cli/ line
edit(f"{ROOT}/src/sqlseed/AGENTS.md",
     "├── cli/              # Click commands: fill, preview, inspect, init, replay, ai-suggest (4 files)\n",
     "")

# __init__.py comment
edit(f"{ROOT}/src/sqlseed/AGENTS.md",
     "├── __init__.py       # Public API: fill, connect, fill_from_config, preview\n",
     "├── __init__.py       # Public API: fill, connect, fill_from_config, preview, load_config\n")

# Optional deps
edit(f"{ROOT}/src/sqlseed/AGENTS.md",
     "- **Optional deps**: try/except for mimesis, psycopg, pymysql (faker is required)\n",
     "- **Optional deps**: mimesis, rich, tqdm use try/except lazy import (faker, rstr, sqlalchemy are required core dependencies); base provider has no optional dependencies\n")

# =====================================================================
# 9. src/sqlseed/_utils/AGENTS.md
# =====================================================================
edit(f"{ROOT}/src/sqlseed/_utils/AGENTS.md",
     "| `paths.py` | `get_cache_dir(subdir)` platform-standard cache directory (macOS/Linux/Windows), `SQLSEED_CACHE_DIR` environment variable takes highest priority, shared by SnapshotManager and AiConfigRefiner |",
     "| `paths.py` | `get_cache_dir(subdir)` platform-standard cache directory; `validate_db_target()` / `validate_table_name()` shared by MCP packages; `SQLSEED_CACHE_DIR` env variable takes highest priority |")

edit(f"{ROOT}/src/sqlseed/_utils/AGENTS.md",
     "- `rich>=13.0` — progress bar (terminal backend)\n- `tqdm` — progress bar (Jupyter backend, optional, installed via `sqlseed[notebook]`)",
     "- `rich>=13.0` — progress bar (terminal backend, optional)\n- `tqdm` — progress bar (Jupyter backend, optional, installed via `sqlseed[notebook]`)")

# =====================================================================
# 10. src/sqlseed/generators/AGENTS.md
# =====================================================================
edit(f"{ROOT}/src/sqlseed/generators/AGENTS.md",
     "31 generators across 3 providers: base (no deps), faker (optional), mimesis (optional).",
     "31 generators across 3 providers: base (no optional deps), faker (required), mimesis (optional).")

edit(f"{ROOT}/src/sqlseed/generators/AGENTS.md",
     "- **NEVER** import faker/mimesis/rstr at module top → use try/except (lazy import)",
     "- **NEVER** import mimesis at module top → use try/except (lazy import). Faker and rstr are required core dependencies, imported at module top. faker_provider uses guarded import for graceful degradation.")

edit(f"{ROOT}/src/sqlseed/generators/AGENTS.md",
     "| `base_provider.py` | BaseProvider — 31 generators, lazy deps |",
     "| `base_provider.py` | BaseProvider — 31 generators, no optional deps |")

# =====================================================================
# 11. src/sqlseed/database/AGENTS.md
# =====================================================================
edit(f"{ROOT}/src/sqlseed/database/AGENTS.md",
     "├── _helpers.py            # fetch_index_info, fetch_sample_rows, apply_bulk_optimize/restore",
     "├── _helpers.py            # fetch_index_info, fetch_sample_rows, batch_insert_rows, apply_bulk_optimize/restore")

# =====================================================================
# 12. plugins/sqlseed-cli/src/sqlseed_cli/AGENTS.md
# =====================================================================
edit(f"{ROOT}/plugins/sqlseed-cli/src/sqlseed_cli/AGENTS.md",
     "| `main.py` | CLI entry point; defines the `cli` group and core subcommands (fill, preview, inspect, init, replay) |",
     "| `main.py` | CLI entry point; defines the `cli` group and core subcommands (fill, preview, inspect, init, replay) |")
# actually inspect is already there; no change needed per checklist (核对无误则不动) — but wait, the checklist says "补 inspect". Looking at the file, it already lists inspect. So no change.

# =====================================================================
# 13. plugins/sqlseed-ai/AGENTS.md
# =====================================================================
edit(f"{ROOT}/plugins/sqlseed-ai/AGENTS.md",
     "└── examples.py       # Few-shot examples for prompts",
     "├── ai_mediator.py    # AI suggestion mediation\n├── mcp.py             # MCP server with 4 AI tools\n├── cli/\n│   └── ai_commands.py # ai-suggest subcommand\n└── examples.py        # Few-shot examples for prompts")

edit(f"{ROOT}/plugins/sqlseed-ai/AGENTS.md",
     "```\nsqlseed-ai/\n├── pyproject.toml        # Separate package: sqlseed>=0.1.0, openai>=1.0, httpx>=0.24.0\n```",
     "```\nsqlseed-ai/\n├── pyproject.toml        # Separate package: sqlseed>=0.1.0, sqlseed-cli>=0.1.0, openai>=1.0, httpx>=0.24.0; optional mcp>=1.0,<2\n```")

edit(f"{ROOT}/plugins/sqlseed-ai/AGENTS.md",
     "| Modify Gemma tools | `_tools.py` | `GEMMA_TOOLS` function declarations |\n| Change error handling | `errors.py` | `summarize_error()` with 7 processors |",
     "| Modify Gemma tools | `_tools.py` | `GEMMA_TOOLS` function declarations |\n| Add AI mediation | `ai_mediator.py` | `apply_ai_suggestions()` hookimpl |\n| Add MCP tool | `mcp.py` | `@mcp.tool()` decorators for AI MCP server |\n| Add CLI subcommand | `cli/ai_commands.py` | `ai-suggest` registration |\n| Change error handling | `errors.py` | `summarize_error()` with 7 processors |")

# =====================================================================
# 14. plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md
# =====================================================================
# Key files add ai_mediator, mcp, cli/ai_commands
edit(f"{ROOT}/plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md",
     "| `examples.py` | Few-shot examples for LLM schema-analysis prompts |",
     "| `ai_mediator.py` | `apply_ai_suggestions()` hookimpl, AI mediation entry point |\n| `mcp.py` | MCP server: 4 AI tools (`sqlseed_ai_generate_yaml`, `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, `sqlseed_list_gemma_models`) |\n| `cli/ai_commands.py` | `ai-suggest` CLI subcommand |\n| `examples.py` | Few-shot examples for LLM schema-analysis prompts |")

# Hooks list add sqlseed_apply_ai_suggestions
edit(f"{ROOT}/plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md",
     "- `AISqlseedPlugin` implements `hookimpl` for `sqlseed_ai_analyze_table` (full-table analysis) and `sqlseed_pre_generate_templates` (per-column value generation for non-simple columns). It does NOT implement `sqlseed_register_providers` or `sqlseed_register_column_mappers`.",
     "- `AISqlseedPlugin` implements `hookimpl` for `sqlseed_ai_analyze_table`, `sqlseed_apply_ai_suggestions`, and `sqlseed_pre_generate_templates`. It does NOT implement `sqlseed_register_providers` or `sqlseed_register_column_mappers`.")

# SQLSEED_AI_TIMEOUT default
edit(f"{ROOT}/plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md",
     "| `SQLSEED_AI_TIMEOUT` | `timeout` | Default 60.0 |",
     "| `SQLSEED_AI_TIMEOUT` | `timeout` | Default `0` (auto-resolve: 60s cloud / 120s local / 300s local reasoning models) |")

# Test command
edit(f"{ROOT}/plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md",
     "```bash\npytest tests/test_ai_plugin.py tests/test_refiner.py\n```",
     "```bash\npytest plugins/sqlseed-ai/tests/\n```")

# Internal deps add sqlseed_cli
edit(f"{ROOT}/plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md",
     "- `sqlseed` (core, generators, plugins hookspecs, `_utils.logger`, `_utils.paths`, `config.models.TableConfig`, `core.orchestrator.DataOrchestrator`)",
     "- `sqlseed` (core, generators, plugins hookspecs, `_utils.logger`, `_utils.paths`, `config.models.TableConfig`, `core.orchestrator.DataOrchestrator`)\n- `sqlseed_cli` (cross-plugin import for `sanitize_table_config()`)")

# =====================================================================
# 15. plugins/sqlseed-ai/README.md
# =====================================================================
# LM Studio URL fix
edit(f"{ROOT}/plugins/sqlseed-ai/README.md",
     "| `AIBackend.LM_STUDIO` | LM Studio | `http://localhost:1234/v1` |",
     "| `AIBackend.LM_STUDIO` | LM Studio | `http://127.0.0.1:1234/v1` |")

# Requirements
edit(f"{ROOT}/plugins/sqlseed-ai/README.md",
     "- `sqlseed >= 0.1.0`\n- `openai >= 1.0`\n- An OpenAI-compatible API key or Google AI Studio API key",
     "- `sqlseed >= 0.1.0`\n- `sqlseed-cli >= 0.1.0`\n- `openai >= 1.0`\n- `httpx >= 0.24.0`\n- An OpenAI-compatible API key or Google AI Studio API key")

# Hooks table add sqlseed_apply_ai_suggestions
edit(f"{ROOT}/plugins/sqlseed-ai/README.md",
     """| Hook | Purpose |
|:-----|:--------|
| `sqlseed_ai_analyze_table` | LLM-driven table analysis, returns column configs |
| `sqlseed_pre_generate_templates` | Pre-generate candidate values for complex columns |""",
     """| Hook | Purpose |
|:-----|:--------|
| `sqlseed_ai_analyze_table` | LLM-driven table analysis, returns column configs |
| `sqlseed_apply_ai_suggestions` | High-level AI mediation (orchestrator entry) |
| `sqlseed_pre_generate_templates` | Pre-generate candidate values for complex columns |""")

# Remove --backend from quickstart
edit(f"{ROOT}/plugins/sqlseed-ai/README.md",
     "# Use local LM Studio\nsqlseed ai-suggest app.db --table users -o users.yaml --backend lm_studio --model google/gemma-4-e4b",
     "# Use local LM Studio\nSQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table users -o users.yaml --model google/gemma-4-e4b")

# SQLSEED_AI_TIMEOUT default
edit(f"{ROOT}/plugins/sqlseed-ai/README.md",
     "| `SQLSEED_AI_TIMEOUT` | — | (auto by backend: 60s cloud, 120s local) | API timeout (seconds) |",
     "| `SQLSEED_AI_TIMEOUT` | — | `0` (auto-resolve: 60s cloud / 120s local / 300s local reasoning models) | API timeout (seconds) |")

# CLI options remove --backend, keep --timeout
edit(f"{ROOT}/plugins/sqlseed-ai/README.md",
     """--model, -m       Model name (overrides auto-selection)
--api-key         API key (overrides env)
--base-url        API base URL (overrides env)
--max-retries     Self-correction rounds (default: 3, 0=disable)
--verify/--no-verify  Toggle self-correction (default: verify)
--no-cache        Skip file cache
--timeout         API timeout in seconds (auto by backend: 60s cloud, 120s local)""",
     """--model, -m       Model name (overrides auto-selection)
--api-key         API key (overrides env)
--base-url        API base URL (overrides env)
--max-retries     Self-correction rounds (default: 3, 0=disable)
--verify/--no-verify  Toggle self-correction (default: verify)
--no-cache        Skip file cache
--timeout         API timeout in seconds (default: auto-resolve per backend)""")

# GEMMA_TOOLS description
edit(f"{ROOT}/plugins/sqlseed-ai/README.md",
     "1. **Tool Definition**: `GEMMA_TOOLS` declares an `analyze_schema` function with a strict JSON Schema describing each parameter (table_name, columns, foreign_keys, indexes, etc.).\n2. **Request**: The schema context and analysis prompt are sent to the Gemma 4 model with `tools=[GEMMA_TOOLS]` and `tool_config` set to force a function call.",
     "1. **Tool Definition**: `GEMMA_TOOLS` declares an `analyze_schema` function with a strict JSON Schema describing each parameter (table_name, columns, foreign_keys, indexes, etc.).\n2. **Request**: The schema context and analysis prompt are sent to the Gemma 4 model with `tools=[GEMMA_TOOLS]` and `tool_choice=\"auto\"`. If tool calling is unsupported, the request falls back to JSON mode or plain text.")

# =====================================================================
# 16. plugins/sqlseed-ai/README.zh-CN.md
# =====================================================================
edit(f"{ROOT}/plugins/sqlseed-ai/README.zh-CN.md",
     "| `AIBackend.LM_STUDIO` | LM Studio | `http://localhost:1234/v1` |",
     "| `AIBackend.LM_STUDIO` | LM Studio | `http://127.0.0.1:1234/v1` |")

edit(f"{ROOT}/plugins/sqlseed-ai/README.zh-CN.md",
     "- `sqlseed >= 0.1.0`\n- `openai >= 1.0`\n- OpenAI 兼容 API Key 或 Google AI Studio API Key",
     "- `sqlseed >= 0.1.0`\n- `sqlseed-cli >= 0.1.0`\n- `openai >= 1.0`\n- `httpx >= 0.24.0`\n- OpenAI 兼容 API Key 或 Google AI Studio API Key")

edit(f"{ROOT}/plugins/sqlseed-ai/README.zh-CN.md",
     """| Hook | 用途 |
|:-----|:-----|
| `sqlseed_ai_analyze_table` | LLM 驱动的表分析，返回列配置 |
| `sqlseed_pre_generate_templates` | 为复杂列预生成候选值 |""",
     """| Hook | 用途 |
|:-----|:-----|
| `sqlseed_ai_analyze_table` | LLM 驱动的表分析，返回列配置 |
| `sqlseed_apply_ai_suggestions` | 高层 AI 中介（orchestrator 入口） |
| `sqlseed_pre_generate_templates` | 为复杂列预生成候选值 |""")

edit(f"{ROOT}/plugins/sqlseed-ai/README.zh-CN.md",
     "# 使用本地 LM Studio\nsqlseed ai-suggest app.db --table users -o users.yaml --backend lm_studio --model google/gemma-4-e4b",
     "# 使用本地 LM Studio\nSQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table users -o users.yaml --model google/gemma-4-e4b")

edit(f"{ROOT}/plugins/sqlseed-ai/README.zh-CN.md",
     "| `SQLSEED_AI_TIMEOUT` | — | （按后端自动：云端 60s，本地 120s） | API 超时（秒） |",
     "| `SQLSEED_AI_TIMEOUT` | — | `0`（自动解析：云端 60s / 本地 120s / 本地推理模型 300s） | API 超时（秒） |")

edit(f"{ROOT}/plugins/sqlseed-ai/README.zh-CN.md",
     """--model, -m       模型名称（覆盖自动选择）
--api-key         API Key（覆盖环境变量）
--base-url        API Base URL（覆盖环境变量）
--max-retries     自纠正轮数（默认: 3，0=禁用）
--verify/--no-verify  切换自纠正（默认: verify）
--no-cache        跳过文件缓存
--timeout         API 超时秒数（按后端自动：云端 60s，本地 120s）""",
     """--model, -m       模型名称（覆盖自动选择）
--api-key         API Key（覆盖环境变量）
--base-url        API Base URL（覆盖环境变量）
--max-retries     自纠正轮数（默认: 3，0=禁用）
--verify/--no-verify  切换自纠正（默认: verify）
--no-cache        跳过文件缓存
--timeout         API 超时秒数（默认: 按后端自动解析）""")

edit(f"{ROOT}/plugins/sqlseed-ai/README.zh-CN.md",
     "1. **工具定义**：`GEMMA_TOOLS` 声明 `analyze_schema` 函数，使用严格的 JSON Schema 描述每个参数（table_name、columns、foreign_keys、indexes 等）。\n2. **请求发送**：将 Schema 上下文和分析 Prompt 发送给 Gemma 4 模型，附带 `tools=[GEMMA_TOOLS]` 和 `tool_config` 设置为强制函数调用。",
     "1. **工具定义**：`GEMMA_TOOLS` 声明 `analyze_schema` 函数，使用严格的 JSON Schema 描述每个参数（table_name、columns、foreign_keys、indexes 等）。\n2. **请求发送**：将 Schema 上下文和分析 Prompt 发送给 Gemma 4 模型，附带 `tools=[GEMMA_TOOLS]` 和 `tool_choice=\"auto\"`。若工具调用不受支持，则回退至 JSON 模式或纯文本。")

# =====================================================================
# 17. plugins/mcp-server-sqlseed/AGENTS.md
# =====================================================================
edit(f"{ROOT}/plugins/mcp-server-sqlseed/AGENTS.md",
     "├── tests/                            # pytest suite (test_server.py, test_validate_db_path.py)",
     "├── tests/                            # pytest suite (test_server.py, test_validate_db_path.py, test_config.py)")

# =====================================================================
# 18. plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/AGENTS.md
# =====================================================================
# Full rewrite per checklist
edit(f"{ROOT}/plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/AGENTS.md",
     """<!-- Parent: ../../AGENTS.md -->
**Generated:** 2026-06-21

# mcp_server_sqlseed

## Purpose

FastMCP server implementation. Provides AI assistants with sqlseed's data generation tools.

## Key Files

| File | Description |
|------|-------------|
| `server.py` | MCP tool definitions (`@mcp.tool()` decorators), core business logic |
| `config.py` | `MCPServerConfig` server configuration (db_path, host, port) |
| `__main__.py` | Server startup entry point |
| `__init__.py` | Package entry, exports `main` function |

## MCP Interface Contract

### Resources

| URI Pattern | Handler | Return Type | Description |
|-------------|---------|-------------|-------------|
| `sqlseed://schema/{db_path}/{table_name}` | `get_schema_resource` | `str` (JSON) | Get schema info for a single table |

### Tools

| Tool Name | Parameters | Return Type | Description |
|-----------|------------|-------------|-------------|
| `sqlseed_inspect_schema` | `db_path: str`, `table_name: str | None = None` | `dict[str, Any]` | Inspect database schema (includes schema_hash) |
| `sqlseed_generate_yaml` | `db_path: str`, `table_name: str`, `max_retries: int = 3`, `api_key: str | None = None`, `base_url: str | None = None`, `model: str | None = None` | `str` (YAML or error text) | AI-generate YAML config |
| `sqlseed_execute_fill` | `db_path: str`, `table_name: str`, `count: int = 1000`, `yaml_config: str | None = None`, `enrich: bool = False` | `dict[str, Any]` | Execute data filling |
| `sqlseed_gemma4_analyze` | `db_path: str`, `table_name: str`, `model: str | None = None`, `backend: str | None = None` | `dict[str, Any]` | Gemma 4 analyzes table structure and recommends config |
| `sqlseed_gemma4_agent_fill` | `db_path: str`, `table_name: str`, `count: int = 1000`, `model: str | None = None`, `backend: str | None = None`, `max_retries: int = 3` | `dict[str, Any]` | Gemma 4 end-to-end: analyze → generate → fill |
| `sqlseed_list_gemma_models` | (no parameters) | `dict[str, Any]` | List Gemma 4 model variants and backends |

- `_validate_db_target()` validates that the extension must be `.db`, `.sqlite`, or `.sqlite3`
- `_MAX_YAML_CONFIG_SIZE = 256 * 1024` (256KB) limits the YAML config size
- `MCPServerConfig` defines `host`/`port` fields, used by `FastMCP()` initialization in `server.py` via `config.host`/`config.port`
- MCP's `_compute_schema_hash()` uses the first 16 characters of SHA256, same as the AI plugin's `_compute_schema_hash()` — they are separate functions in different modules but use the same truncation length

## For AI Agents

### Working In This Directory

- Adding a new MCP tool requires registering it in `server.py` with `@mcp.tool()`
- All user input must pass through validation functions (`_validate_db_target` validates path extension and existence, `_validate_table_name` validates that the table exists in the database)
- YAML config has a size limit (`_MAX_YAML_CONFIG_SIZE`) to prevent oversized input
- AI features are gated by the `_AI_AVAILABLE` flag; when unavailable, it degrades to non-AI mode
- The server layer should stay thin; delegate business logic to `sqlseed.core.orchestrator` and `sqlseed_ai`

### Testing Requirements

```bash
pip install -e "./plugins/mcp-server-sqlseed"
pytest
```

### Common Patterns

- MCP tool definition: `@mcp.tool()` decorator registers the tool; parameters are auto-inferred from the function signature
- Input validation: `_validate_db_target()` + `_validate_table_name()` double validation
- AI fallback: `try: from sqlseed_ai import ... except ImportError: _AI_AVAILABLE = False`

## Dependencies

### Internal

- `sqlseed` (core.orchestrator, config.loader, config.models)
- `sqlseed_ai` (optional, SchemaAnalyzer, AiConfigRefiner)

### External

- `mcp>=1.0,<2` — MCP server framework

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->""",
     """<!-- Parent: ../../AGENTS.md -->
**Generated:** 2026-07-29

# mcp_server_sqlseed

## Purpose

FastMCP server implementation exposing sqlseed core capabilities (rule-driven YAML generation + data fill). No LLM dependency.

## Key Files

| File | Description |
|------|-------------|
| `server.py` | 2 MCP tools (`@mcp.tool()`): `sqlseed_generate_yaml` (rule-driven), `sqlseed_execute_fill` |
| `config.py` | `MCPServerConfig` (host, port) |
| `__main__.py` | Server startup entry point |
| `__init__.py` | Package entry, exports `main` function |

## MCP Interface Contract

### Tools

| Tool Name | Parameters | Return Type | Description |
|-----------|------------|-------------|-------------|
| `sqlseed_generate_yaml` | `db_path: str`, `table_name: str` | `str` (YAML or `# Error: …`) | Rule-driven YAML config via `ColumnMapper` (no LLM) |
| `sqlseed_execute_fill` | `db_path: str`, `table_name: str`, `count: int = 1000`, `yaml_config: str | None = None`, `enrich: bool = False` | `dict[str, Any]` or `{"error": …}` | Execute data generation |

- Validation: `_validate_db_target()` and `_validate_table_name()` from `sqlseed._utils.paths`
- `_MAX_YAML_CONFIG_SIZE = 256 * 1024` (256KB) YAML input limit
- `MCPServerConfig` defaults: host=`127.0.0.1`, port=`8000`
- Errors returned as `# Error: {msg}` string (generate_yaml) or `{"error": msg}` dict (execute_fill)

## For AI Agents

### Working In This Directory

- This package has **no AI dependency**; AI tools live in `sqlseed-ai[mcp]` (`sqlseed_ai.mcp`)
- The server layer stays thin; delegate to `sqlseed.core.orchestrator`
- Always validate inputs with `_validate_db_target()` / `_validate_table_name()` before DB operations

### Testing Requirements

```bash
pip install -e "./plugins/mcp-server-sqlseed"
pytest plugins/mcp-server-sqlseed/tests/
```

### Common Patterns

- `@mcp.tool()` registers tools; parameters inferred from function signatures
- Return JSON-serializable values from tool functions

## Dependencies

### Internal

- `sqlseed` (core.orchestrator, config.models)

### External

- `mcp>=1.0,<2` — MCP server framework

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->""")

# =====================================================================
# 19. tests/AGENTS.md
# =====================================================================
edit(f"{ROOT}/tests/AGENTS.md",
     """├── test_cli.py              # CLI tests
├── test_cli_yaml_priority.py    # CLI YAML priority tests
├── test_ai_plugin.py        # AI plugin integration tests
├── test_core/               # Core module tests
├── test_generators/         # Generator tests
├── test_database/           # Database adapter tests
├── test_config/             # Config tests
├── test_plugins/            # Plugin tests
├── test_utils/              # Utility tests
└── benchmarks/              # Performance benchmarks""",
     """├── test_core/               # Core module tests
├── test_generators/         # Generator tests
├── test_database/           # Database adapter tests
├── test_config/             # Config tests
├── test_plugins/            # Plugin tests
├── test_utils/              # Utility tests
├── benchmarks/              # Performance benchmarks
└── integration/             # Integration tests (migrated: test_cli, test_cli_yaml_priority, test_ai_plugin moved to plugin dirs)""")

edit(f"{ROOT}/tests/AGENTS.md",
     """├── conftest.py              # Fixtures: tmp_db, tmp_db_with_data, unique_test_db
├── _helpers.py              # Test utilities
├── test_public_api.py       # Public API tests (fill, connect, preview)
├── test_orchestrator.py     # DataOrchestrator tests
├── test_mapper.py           # ColumnMapper tests
├── test_schema.py           # SchemaInferrer tests
├── test_relation.py         # RelationResolver tests
├── test_result.py           # GenerationResult tests
├── test_refiner.py          # AI refiner tests
├── test_enrich_enum_detection.py  # Enrichment tests""",
     """├── conftest.py              # Fixtures: tmp_db, tmp_db_with_data, unique_test_db, gc_between_tests (opt-in)
├── _helpers.py              # Test utilities
├── _ai_helpers.py           # AI plugin test helpers
├── test_public_api.py       # Public API tests (fill, connect, preview)
├── test_orchestrator.py     # DataOrchestrator tests
├── test_orchestrator_adapter.py # Multi-DB adapter tests
├── test_url_connection.py   # URL connection tests
├── test_mapper.py           # ColumnMapper tests
├── test_mapper_camelcase.py # CamelCase mapping tests
├── test_schema.py           # SchemaInferrer tests
├── test_relation.py         # RelationResolver tests
├── test_result.py           # GenerationResult tests
├── test_refiner.py          # AI refiner tests
├── test_enrich_enum_detection.py  # Enrichment tests
├── test_hardware.py         # Hardware detection tests
├── test_doc_sync.py         # Documentation sync tests
├── test_architecture.py     # Architecture alignment tests""")

edit(f"{ROOT}/tests/AGENTS.md",
     """## CONVENTIONS

- **Naming**: `test_<module>.py` mirrors `src/sqlseed/<module>/`
- **Fixtures**: Use `tmp_db`, `tmp_db_with_data`, `unique_test_db` from conftest
- **DB creation**: Use `create_simple_db()`, `create_project_info_db()` helpers
- **Orchestrator tests**: Use `DataOrchestrator` as context manager
- **Type hints**: Relaxed in tests (mypy overrides in pyproject.toml)

## ANTI-PATTERNS

- **NEVER** hardcode DB paths → use `tmp_path` fixture
- **NEVER** skip cleanup → use context managers or fixtures
- **ALWAYS** use `provider="base"` in tests (no external deps)
- **ALWAYS** use `gc.collect()` between tests (autouse fixture)""",
     """## CONVENTIONS

- **Naming**: `test_<module>.py` mirrors `src/sqlseed/<module>/`
- **Fixtures**: Use `tmp_db`, `tmp_db_with_data`, `unique_test_db` from root `conftest.py`
- **DB creation**: Use `create_simple_db()`, `create_project_info_db()` helpers
- **Orchestrator tests**: Use `DataOrchestrator` as context manager
- **Type hints**: Relaxed in tests (mypy overrides in pyproject.toml)

## ANTI-PATTERNS

- **NEVER** hardcode DB paths → use `tmp_path` fixture
- **NEVER** skip cleanup → use context managers or fixtures
- **ALWAYS** use `provider="base"` in tests (no external deps)
- **`gc.collect()`** is opt-in, not autouse""")

# =====================================================================
# 20. tests/benchmarks/AGENTS.md
# =====================================================================
edit(f"{ROOT}/tests/benchmarks/AGENTS.md",
     "| `bench_fill.py` | Benchmark tests for the `fill` function |",
     "| `bench_fill.py` | Benchmark tests for `fill` and `preview` |")

edit(f"{ROOT}/tests/benchmarks/AGENTS.md",
     "- Test scenarios: 1K rows, 10K rows, provider comparison",
     "- Test scenarios: 1K fill, 10K fill, 5-row preview (provider=base); no cross-provider comparison")

# =====================================================================
# 21. tests/test_database/AGENTS.md
# =====================================================================
edit(f"{ROOT}/tests/test_database/AGENTS.md",
     "| `test_helpers.py` | Database helper function tests |",
     "| `test_helpers.py` | Database helper function tests |")
# The checklist says "补 conftest.py". Let me check if it's already there.
# In the file read earlier, there is no conftest.py listed. Add it.
edit(f"{ROOT}/tests/test_database/AGENTS.md",
     "| `test_sql_safe.py` | SQL injection protection tests |",
     "| `test_sql_safe.py` | SQL injection protection tests |\n| `conftest.py` | Database-layer fixtures (raw_adapter, etc.) |")

# =====================================================================
# 22. tests/test_generators/AGENTS.md
# =====================================================================
edit(f"{ROOT}/tests/test_generators/AGENTS.md",
     "- Faker/Mimesis tests must use `pytest.importorskip` to handle missing optional dependencies\n- Generator tests must verify seed reproducibility\n- Dispatch sync tests ensure `GENERATOR_MAP` consistency across providers",
     "- `pytest.importorskip` is used only in `test_registry.py` for lazy-load testing\n- Generator tests must verify seed reproducibility\n- Dispatch sync tests ensure `GENERATOR_MAP` consistency across providers")

edit(f"{ROOT}/tests/test_generators/AGENTS.md",
     "- Optional dependency tests use `pytest.importorskip(\"faker\")` / `pytest.importorskip(\"mimesis\")`",
     "")

print("All edits completed.")
