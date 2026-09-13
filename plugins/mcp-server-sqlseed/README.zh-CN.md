# mcp-server-sqlseed

[English](https://github.com/sunbos/sqlseed/blob/main/plugins/mcp-server-sqlseed/README.md) |
**[中文](https://github.com/sunbos/sqlseed/blob/main/plugins/mcp-server-sqlseed/README.zh-CN.md)**

为 [sqlseed](https://sunbos.github.io/sqlseed/) 提供
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 工具：从数据库结构推导
YAML 配置，再生成测试数据。两个工具均使用离线 Core 规则，无需 LLM。

## 安装

本文描述当前五包源码。兼容版本发布到 PyPI 前，在 Python 3.10+ 虚拟环境中，
从仓库根一次安装本地 Core 与 MCP：

```bash
python -m pip install -e . -e ./plugins/mcp-server-sqlseed
```

Core 0.2.3 缺少当前入口使用的数据库目标校验接口。匹配版本发布后，
才可使用软件源安装命令：

```bash
python -m pip install "mcp-server-sqlseed>=0.2.4.dev0,<0.3"
```

## MCP 客户端配置

在 Claude Desktop、Cursor 等客户端中，使用安装该包的环境提供的可执行文件：

```json
{
  "mcpServers": {
    "sqlseed": {
      "command": "mcp-server-sqlseed"
    }
  }
}
```

客户端没有继承该环境的 PATH 时，使用可执行文件的绝对路径。
服务器通过 stdio 运行，也支持 `python -m mcp_server_sqlseed`。

## MCP Tools

| Tool | 输入与结果 |
| --- | --- |
| `sqlseed_generate_yaml` | 接收 `db_path` 与 `table_name`，返回规则驱动的 YAML 字符串 |
| `sqlseed_execute_fill` | 接收 `db_path`、`table_name`、`count=1000`、可选 `yaml_config` 和 `enrich=False`，返回表名、已提交数量、耗时与错误 |

`db_path` 接受已存在的 SQLite `.db`、`.sqlite`、`.sqlite3` 文件或数据库 URL。
使用 PostgreSQL 时需在同一环境安装 Core 的 `postgres` extra。目标表必须已存在。
列映射由 Core 规则确定，两个工具都不会向模型发送请求。

提供 `yaml_config` 时，其内容必须为 YAML mapping，并包含所请求的表。
空文档、未知目标表或不包含目标表的配置会在生成前失败；UTF-8 编码后上限为 256 KiB。
工具参数决定数据库、表、生成行数和 enrich；YAML 仅提供匹配表的列规则、seed 与
`clear_before`，不覆盖工具参数指定的范围。

## 使用示例与失败结果

配置客户端后，可以请求为现有数据库中的表准备规则。例如：

> “为 `app.db` 的 `users` 表生成 YAML 配置，供我审阅。”

通常按以下步骤操作：

1. 调用 `sqlseed_generate_yaml`，得到规则驱动的 YAML。
2. 审阅列规则、目标数据库与期望行数。
3. 明确执行后调用 `sqlseed_execute_fill`，检查 `errors` 和实际已提交的 `count`。

后续批次失败时，之前已提交的批次可能保留。YAML 工具对已处理的错误返回
`# Error: ...`，fill 工具对已处理的请求错误返回 `error` 字段。
MCP 传输成功不等于配置或填充成功，需要检查返回内容。

## 独立 AI MCP 服务器

本包仅提供上述两个工具，不提供 schema resource 或独立 schema-inspection 工具。
LLM 分析属于另一个 AI MCP 进程。使用当前源码时，一次安装本地 Core、CLI 与 AI extra：

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e "./plugins/sqlseed-ai[mcp]"
mcp-server-sqlseed-ai
```

匹配版本发布后，可安装 `"sqlseed-ai[mcp]>=0.2.4.dev0,<0.3"`。
AI YAML 工具名为 `sqlseed_ai_generate_yaml`，命令入口为 `mcp-server-sqlseed-ai`；
另有 `sqlseed_gemma4_analyze`、`sqlseed_gemma4_agent_fill` 和 `sqlseed_list_gemma_models`。
需要两组工具时，客户端分别配置两个服务器，并为 AI 进程提供后端设置。
安装 AI 包不会向规则型服务器注入工具，旧 `mcp-server-sqlseed[ai]` extra 不适用于当前布局。

## 依赖

- Python `>=3.10`
- `sqlseed>=0.2.4.dev0,<0.3`
- `mcp>=1.0,<2`

更多信息见[用户指南](https://sunbos.github.io/sqlseed/guide/)、
[升级说明](https://sunbos.github.io/sqlseed/migration.zh-CN/)和
[服务器源码](https://github.com/sunbos/sqlseed/tree/main/plugins/mcp-server-sqlseed)。

许可证：[AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE)。
发行包包含完整 LICENSE 文本。
