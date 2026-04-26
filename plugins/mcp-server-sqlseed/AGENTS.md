# AGENTS.md — plugins/mcp-server-sqlseed

## 作用域

- 本目录是可选分发包 `mcp-server-sqlseed`，源码在 `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/`。
- 包入口是 `mcp-server-sqlseed = "mcp_server_sqlseed:main"`，模块入口是 `python -m mcp_server_sqlseed`。
- 依赖：`sqlseed>=0.1.0`、`mcp>=1.0`。可选依赖：`ai = ["sqlseed-ai"]`。

## 文件清单

| 文件 | 职责 |
|------|------|
| `__init__.py` | `main()` — 调用 `mcp.run()` 启动 MCP 服务器 |
| `__main__.py` | 支持 `python -m mcp_server_sqlseed` 启动 |
| `config.py` | `MCPServerConfig(BaseModel)` — 预留配置（db_path、host、port），当前未被 server.py 使用 |
| `server.py` | FastMCP 服务器实例（`mcp = FastMCP("sqlseed")`）、3 个工具 + 1 个资源定义、辅助函数 |

## 本目录规则

- 保持服务器层足够薄。Schema 检查、填充执行和 AI YAML 生成应继续委托给 `sqlseed.core.orchestrator` 与 `sqlseed_ai`，不要在这里复制主包编排逻辑。
- 把 tool 名称、resource URI 形状和返回 payload 视为客户端契约。
- 返回值应保持 JSON/YAML 可序列化；`ColumnInfo`、`ForeignKeyInfo` 这类对象要先显式转换（通过 `_serialize_schema_context()`）。
- `sqlseed_generate_yaml` 依赖 `sqlseed-ai`，失败路径应继续返回可读文本，而不是让整个 server 直接崩掉。
- 本包内部使用的 schema hash 只服务 MCP 返回结果，不要默认把它和 AI 插件缓存 hash 当成同一个协议。MCP 的 `_compute_schema_hash()` 使用 SHA256 前 16 字符，AI 插件的 `_compute_schema_hash()` 使用前 12 字符。
- `_MAX_YAML_CONFIG_SIZE = 256 * 1024`（256KB）限制 YAML 配置字符串大小，防止资源滥用。
- `_validate_db_path()` 验证文件扩展名必须为 `.db`、`.sqlite` 或 `.sqlite3`。
- `_validate_table_name()` 检查表名是否在允许列表中。
- `MCPServerConfig` 定义了 `host` 和 `port` 字段，但当前 `server.py` 中未使用，`mcp.run()` 依赖 FastMCP 自身的传输配置。

## MCP 接口契约

### 资源

| URI 模式 | 处理函数 | 返回类型 | 说明 |
|----------|----------|----------|------|
| `sqlseed://schema/{db_path}/{table_name}` | `get_schema_resource` | `str` (JSON) | 获取单表 schema 信息 |

### 工具

| 工具名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| `sqlseed_inspect_schema` | `db_path: str`, `table_name: str \| None = None` | `dict[str, Any]` | 检查数据库 schema（含 schema_hash） |
| `sqlseed_generate_yaml` | `db_path: str`, `table_name: str`, `max_retries: int = 3`, `api_key: str \| None = None`, `base_url: str \| None = None`, `model: str \| None = None` | `str` (YAML 或错误文本) | AI 生成 YAML 配置。`api_key`/`base_url`/`model` 参数优先级高于环境变量，用于覆盖 `AIConfig.from_env()` 的默认值 |
| `sqlseed_execute_fill` | `db_path: str`, `table_name: str`, `count: int = 1000`, `yaml_config: str \| None = None`, `enrich: bool = False` | `dict[str, Any]` | 执行数据填充 |

## 评审热点

- `server.py` 同时承担 FastMCP resource 与 tools 定义。改签名或命名会直接影响外部 MCP 客户端。
- 观察到仓库里目前没有专门的 `tests/test_mcp_*` 覆盖；如果你修改这里的行为，至少跑全量 `pytest`，更稳妥的是补专门测试。

## 验证

- 安装插件：`pip install -e "./plugins/mcp-server-sqlseed"`
- 回归检查：`pytest`
