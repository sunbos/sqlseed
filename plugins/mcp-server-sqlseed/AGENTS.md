# mcp-server-sqlseed 包边界

**源码核验日期：** 2026-09-14

本包用 FastMCP 暴露 core 的规则驱动 YAML 生成与数据填充，不依赖 LLM。
实现细节见 [src/mcp_server_sqlseed/AGENTS.md](src/mcp_server_sqlseed/AGENTS.md)。

## 范围与依赖

- distribution 名为 `mcp-server-sqlseed`，Python module 名为 `mcp_server_sqlseed`。
- [pyproject.toml](pyproject.toml) 声明 `sqlseed>=0.2.4.dev0,<0.3`、`mcp>=1.0,<2`；console script 指向 `mcp_server_sqlseed:main`。Core 0.2.3 缺少入口使用的目标校验函数，不兼容当前 MCP。
- 仅提供 `sqlseed_generate_yaml`、`sqlseed_execute_fill`；不提供 schema resource 或独立 schema-inspect 工具。
- AI 工具属于 [sqlseed-ai](../sqlseed-ai/AGENTS.md) 的 `sqlseed_ai.mcp`；不要在本包导入 `sqlseed_ai`。
- 区分两类 MCP 的依据是是否需要 LLM runtime，不是部署位置或是否联网；当前启动入口调用 `mcp.run()`，使用 stdio。配置中的 host / port 不代表入口已经提供 HTTP transport 切换。
- 依赖变化后，在本包目录执行 `uv lock`，使 [uv.lock](uv.lock) 与 manifest 同步。

## 测试与验证

先按[根指南](../../AGENTS.md#安装与运行)统一安装本地包，再从仓库根执行：

```bash
pytest plugins/mcp-server-sqlseed/tests/
ruff check plugins/mcp-server-sqlseed/
ruff format --check plugins/mcp-server-sqlseed/
mypy plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/
```

- `tests/test_server.py` 检查真实 YAML → fill 往返与数据库行数；`test_validate_db_path.py` 检查路径/URL；`test_config.py` 检查 Pydantic 配置。
- `tests/test_yaml_execution_validation.py` 检查无效 YAML 不写库及多表 YAML 的目标隔离；`test_stdio_progress.py` 检查真实 fill 的 stdout 不含 Core 进度输出。
- SQLite 测试使用 `tmp_path` 建真实库；本包 `tests/conftest.py` 提供 `tmp_sqlite_db`，其他共享 fixtures 由仓库根发现。
- PostgreSQL 场景使用根 `pg_url` fixture，外部服务要求以该 fixture 为准。
- pytest 配置继承仓库根；不要添加本包 pytest rootdir 配置，否则会改变共享 fixtures 与 `tests` 包解析。
- 本包 Ruff isort 显式把 `sqlseed` 设为 first-party、插件模块设为 third-party；不要根据当前工作目录反转分类。
