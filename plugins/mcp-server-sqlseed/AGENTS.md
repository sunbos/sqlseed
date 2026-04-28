<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# mcp-server-sqlseed

## Purpose

基于 FastMCP 的 sqlseed MCP 服务器插件。为 AI 助手提供 SQLite 测试数据生成能力。

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | 插件元数据，入口命令 `mcp-server-sqlseed` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/mcp_server_sqlseed/` | 服务器源码（见 `src/mcp_server_sqlseed/AGENTS.md`） |

## For AI Agents

### Working In This Directory

- 保持服务器层足够薄，业务逻辑委托给 `sqlseed.core.orchestrator` 与 `sqlseed_ai`
- MCP 工具名称、资源 URI 和返回 payload 视为客户端契约

### Testing Requirements

```bash
pip install -e "./plugins/mcp-server-sqlseed"
pytest
```

### Common Patterns

- 构建系统：hatchling + hatch-vcs（root 指向项目根目录）
- AI 功能为可选依赖，通过 `sqlseed-ai` extras 安装

## Dependencies

### Internal

- `sqlseed>=0.1.0,<2`

### External

- `mcp>=1.0,<2`
- 可选：`sqlseed-ai`（AI 生成 YAML 功能）

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
