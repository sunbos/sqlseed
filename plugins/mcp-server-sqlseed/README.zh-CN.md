# mcp-server-sqlseed

[English](README.md) | **[中文](README.zh-CN.md)**

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 服务器，用于 [sqlseed](https://github.com/sunbos/sqlseed) — 让 AI 助手直接检查 Schema、生成配置和填充 SQLite 数据库。

## 安装

```bash
# 基础安装
pip install mcp-server-sqlseed

# 含 AI 支持（包含 sqlseed-ai）
pip install mcp-server-sqlseed[ai]
```

## 配置

### Claude Desktop

添加到 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）：

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    }
  }
}
```

### Cursor / 其他 MCP 客户端

使用命令：`mcp-server-sqlseed`

## MCP Tools

| Tool | 说明 |
|:-----|:-----|
| `sqlseed_inspect_schema` | 检查数据库 Schema：列、外键、索引、样本数据、schema_hash。可选 `table_name`（省略则返回所有表）。 |
| `sqlseed_generate_yaml` | AI 驱动的 YAML 配置生成，含自纠正。需要 `sqlseed-ai` 插件和 API Key。支持 `api_key`/`base_url`/`model` 参数覆盖。 |
| `sqlseed_execute_fill` | 执行数据生成。可选 `yaml_config` 字符串、`count` 和 `enrich` 标志。YAML 配置最大 256KB。 |
| `sqlseed_gemma4_analyze` | 使用 Gemma 4 原生函数调用分析表 Schema。支持 `model`/`backend` 参数覆盖。需要 `sqlseed-ai`。 |
| `sqlseed_gemma4_agent_fill` | 端到端 AI Agent：Gemma 4 分析 Schema → 生成配置（自纠正）→ 填充数据。需要 `sqlseed-ai`。 |
| `sqlseed_list_gemma_models` | 列出 Gemma 4 模型变体及硬件兼容性（RAM/GPU/VRAM）、后端可用性和推荐的默认模型/后端。 |

### MCP Resource

| Resource | 说明 |
|:---------|:-----|
| `sqlseed://schema/{db_path}/{table_name}` | 指定表的只读 JSON Schema |

## 使用示例

配置 MCP 客户端后，可以这样提示：

> "检查 `app.db` 的 Schema，为 `users` 表生成 YAML 配置，然后填充 1000 行数据。"

AI 助手会依次调用：
1. `sqlseed_inspect_schema` → 获取表结构
2. `sqlseed_generate_yaml` → 生成 YAML 配置（需安装 sqlseed-ai）
3. `sqlseed_execute_fill` → 填充数据

## AI 集成

当安装了 `sqlseed-ai` 并配置了 API Key（`SQLSEED_AI_API_KEY` 或 `OPENAI_API_KEY`）时，`sqlseed_generate_yaml` 工具使用 LLM 驱动的分析和自纠正。未安装 AI 插件时，该工具返回回退消息。

### Gemma 4 集成

`sqlseed_gemma4_analyze` 和 `sqlseed_gemma4_agent_fill` 工具通过 `GEMMA_TOOLS` 接口（`analyze_schema` 工具，不支持时自动回退 JSON mode）利用 **Gemma 4 Native Function Calling**。它们支持 `sqlseed-ai` 的所有后端（Google AI Studio、LM Studio、Ollama、OpenAI 兼容端点），并接受可选的 `model`/`backend` 参数覆盖。使用 `sqlseed_list_gemma_models` 可查看可用的模型变体、硬件兼容状态和后端可用性。

## 依赖

- Python >= 3.10
- `sqlseed >= 0.1.0`
- `mcp >= 1.0`

可选：
- `sqlseed-ai`（用于 `sqlseed_generate_yaml`、`sqlseed_gemma4_analyze`、`sqlseed_gemma4_agent_fill`、`sqlseed_list_gemma_models` 工具）

## 许可证

AGPL-3.0-or-later
