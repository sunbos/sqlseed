# AGENTS.md — plugins/mcp-server-sqlseed

## 作用域

- 本目录是可选分发包 `mcp-server-sqlseed`，源码在 `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/`。
- 包入口是 `mcp-server-sqlseed = "mcp_server_sqlseed:main"`，模块入口是 `python -m mcp_server_sqlseed`。

## 本目录规则

- 保持服务器层足够薄。Schema 检查、填充执行和 AI YAML 生成应继续委托给 `sqlseed.core.orchestrator` 与 `sqlseed_ai`，不要在这里复制主包编排逻辑。
- 把 tool 名称、resource URI 形状和返回 payload 视为客户端契约。当前公开的是 `sqlseed_inspect_schema`、`sqlseed_generate_yaml`、`sqlseed_execute_fill` 和 `sqlseed://schema/{db_path}/{table_name}`。
- 返回值应保持 JSON/YAML 可序列化；`ColumnInfo`、`ForeignKeyInfo` 这类对象要先显式转换。
- `sqlseed_generate_yaml` 依赖 `sqlseed-ai`，失败路径应继续返回可读文本，而不是让整个 server 直接崩掉。
- 本包内部使用的 schema hash 只服务 MCP 返回结果，不要默认把它和 AI 插件缓存 hash 当成同一个协议。

## 评审热点

- `server.py` 同时承担 FastMCP resource 与 tools 定义。改签名或命名会直接影响外部 MCP 客户端。
- 观察到仓库里目前没有专门的 `tests/test_mcp_*` 覆盖；如果你修改这里的行为，至少跑全量 `pytest`，更稳妥的是补专门测试。

## 验证

- 安装插件：`pip install -e "./plugins/mcp-server-sqlseed"`
- 回归检查：`pytest`
