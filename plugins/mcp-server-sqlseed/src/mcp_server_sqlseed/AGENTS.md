<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# mcp_server_sqlseed

## Purpose

FastMCP 服务器实现。为 AI 助手提供 sqlseed 的数据生成工具。

## Key Files

| File | Description |
|------|-------------|
| `server.py` | MCP 工具定义（`@mcp.tool()` 装饰器），核心业务逻辑 |
| `config.py` | `MCPServerConfig` 服务器配置（db_path, host, port） |
| `__main__.py` | 服务器启动入口 |
| `__init__.py` | 包入口，导出 `main` 函数 |

## MCP 接口契约

### 资源

| URI 模式 | 处理函数 | 返回类型 | 说明 |
|----------|----------|----------|------|
| `sqlseed://schema/{db_path}/{table_name}` | `get_schema_resource` | `str` (JSON) | 获取单表 schema 信息 |

### 工具

| 工具名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| `sqlseed_inspect_schema` | `db_path: str`, `table_name: str | None = None` | `dict[str, Any]` | 检查数据库 schema（含 schema_hash） |
| `sqlseed_generate_yaml` | `db_path: str`, `table_name: str`, `max_retries: int = 3`, `api_key: str | None = None`, `base_url: str | None = None`, `model: str | None = None` | `str` (YAML 或错误文本) | AI 生成 YAML 配置 |
| `sqlseed_execute_fill` | `db_path: str`, `table_name: str`, `count: int = 1000`, `yaml_config: str | None = None`, `enrich: bool = False` | `dict[str, Any]` | 执行数据填充 |

- `_validate_db_path()` 验证扩展名必须为 `.db`、`.sqlite` 或 `.sqlite3`
- `_MAX_YAML_CONFIG_SIZE = 256 * 1024`（256KB）限制 YAML 配置大小
- `MCPServerConfig` 定义了 `host`/`port` 字段但当前 `server.py` 中未使用
- MCP 的 `_compute_schema_hash()` 使用 SHA256 前 16 字符，AI 插件的 `_compute_schema_hash()` 使用前 12 字符，两者是不同模块中的不同函数

## For AI Agents

### Working In This Directory

- 新增 MCP 工具需在 `server.py` 中用 `@mcp.tool()` 注册
- 所有用户输入必须经过验证函数处理（`_validate_db_path` 验证路径扩展名和存在性，`_validate_table_name` 验证表名在数据库中存在）
- YAML 配置有大小限制（`_MAX_YAML_CONFIG_SIZE`），防止过大输入
- AI 功能通过 `_AI_AVAILABLE` 标志控制，不可用时降级为非 AI 模式
- 服务器层应足够薄，业务逻辑委托给 `sqlseed.core.orchestrator` 与 `sqlseed_ai`

### Testing Requirements

```bash
pip install -e "./plugins/mcp-server-sqlseed"
pytest
```

### Common Patterns

- MCP 工具定义：`@mcp.tool()` 装饰器注册工具，参数通过函数签名自动推断 schema
- 输入验证：`_validate_db_path()` + `_validate_table_name()` 双重验证
- AI 降级：`try: from sqlseed_ai import ... except ImportError: _AI_AVAILABLE = False`

## Dependencies

### Internal

- `sqlseed`（core.orchestrator, config.loader, config.models）
- `sqlseed_ai`（可选，SchemaAnalyzer, AiConfigRefiner）

### External

- `mcp>=1.0,<2` — MCP 服务器框架

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
