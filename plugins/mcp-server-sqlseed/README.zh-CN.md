# mcp-server-sqlseed

[English](README.md) | **[中文](README.zh-CN.md)**

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 服务器，用于 [sqlseed](https://github.com/sunbos/sqlseed) — 向 AI 助手暴露**核心能力**（规则驱动的 YAML 生成 + 数据填充），无需 LLM。

## 安装

```bash
pip install mcp-server-sqlseed
```

如需 LLM 驱动的 Schema 分析，请安装独立的 AI MCP 服务器：

```bash
pip install "sqlseed-ai[mcp]"   # 提供 sqlseed_ai_generate_yaml + Gemma 4 工具
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
| `sqlseed_generate_yaml` | 基于 sqlseed `ColumnMapper`（74 条精确规则 + 27 个正则模式）的规则驱动 YAML 配置模板。离线、确定性、无需 LLM。 |
| `sqlseed_execute_fill` | 执行数据生成。可选 `yaml_config` 字符串、`count` 和 `enrich` 标志。YAML 配置最大 256KB。 |

### 不包含的内容

依据 [ARCHITECTURE.md Section 3.4](../../ARCHITECTURE.md)，本服务器仅暴露核心能力：

- ~~`sqlseed_inspect_schema`~~ — 使用第三方 MCP，如 [mcp-database-server](https://github.com/iPraBhu/mcp-database-server) 或 [mcp-db-analyzer](https://github.com/Dmitriusan/mcp-db-analyzer)
- ~~`sqlseed://schema` Resource~~ — Schema 检查由上述 MCP 负责
- ~~`sqlseed_gemma4_analyze` / `sqlseed_gemma4_agent_fill` / `sqlseed_list_gemma_models`~~ — 已移至 `sqlseed-ai[mcp]`
- ~~AI 驱动的 `sqlseed_generate_yaml`~~ — LLM 驱动变体为 `sqlseed_ai_generate_yaml`，位于 `sqlseed-ai[mcp]`

## 使用示例

配置 MCP 客户端后，可以这样提示：

> "为 `app.db` 的 `users` 表生成 YAML 配置，然后填充 1000 行数据。"

AI 助手会依次调用：
1. `sqlseed_generate_yaml` → 规则驱动 YAML 模板（离线）
2. `sqlseed_execute_fill` → 填充数据

## 依赖

- Python >= 3.10
- `sqlseed >= 0.1.0`
- `mcp >= 1.0`

## 许可证

AGPL-3.0-or-later
