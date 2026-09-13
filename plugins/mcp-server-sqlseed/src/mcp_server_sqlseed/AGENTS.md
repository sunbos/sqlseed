# mcp_server_sqlseed 实现

**源码核验日期：** 2026-09-14

上层规则见 [包指南](../../AGENTS.md)。保持 MCP 层轻量：校验输入、委托 core、转换协议结果。

## 接口契约

| `server.py` 工具 | 参数 | 返回值 |
| --- | --- | --- |
| `sqlseed_generate_yaml` | `db_path`、`table_name` | YAML `str`；已捕获错误返回 `# Error: ...` |
| `sqlseed_execute_fill` | `db_path`、`table_name`、`count=1000`、`yaml_config=None`、`enrich=False` | 包含 `table_name`、`count`、`elapsed`、`errors` 的 dict；已捕获错误返回 `{"error": ...}` |

- 两个工具的 `db_path` 参数也接受数据库 URL；不要仅因名称而限制为 SQLite 文件。
- `_validate_db_target` 从 core `_utils.paths` 导入：含 `://` 的 URL 原样交给 adapter；文件必须存在且扩展名为 `.db`/`.sqlite`/`.sqlite3`，返回解析后的路径。
- 创建 orchestrator 后，以 `_validate_table_name(table_name, orch.get_table_names())` 验证目标表存在。
- `@mcp.tool()` 自动从函数签名推导接口；新增/修改参数时同步本包中英文 README 与工具测试，不要把 YAML 工具改成统一 dict 返回值。
- YAML 生成调用 `get_column_mapping()`，通过 `_convert_spec_to_column_entry()` 保留 generator、params、正数 null_ratio；`skip` 映射保留在模板中。
- 执行工具对 YAML 的 UTF-8 字节长度限制为 `_MAX_YAML_CONFIG_SIZE`（256 KiB），再 `yaml.safe_load()` → `GeneratorConfig`。
- 显式提供的 YAML（包括空字符串）必须是 mapping，所有根 key 为字符串，且包含目标表配置，否则在生成前返回既有 `{"error": ...}`。只有 `yaml_config=None` 使用默认映射，不能把空值或表名不匹配静默当作无配置。
- YAML 只从目标 table 配置读取 columns、clear_before、seed；实际连接、table、count、enrich 由工具参数决定，不要误认为整份 YAML 都被执行。
- `fill_table(..., skip_ai=True)` 保证执行路径无 LLM；结果行数读取 `GenerationResult.count`。
- 执行工具局部传入 `NullProgressBackend` 并管理其 context；stdio 的 stdout 只承载 MCP 协议，不得输出 core Rich 进度，也不要全局重定向 stdout 或替换 progress factory。
- 保留两工具各自的错误返回形状；执行工具另外捕获 `yaml.YAMLError`。

## 启动与配置

- [__init__.py](__init__.py) 的 `main()` 调用 `mcp.run()`；[__main__.py](__main__.py) 支持 `python -m mcp_server_sqlseed`。
- [config.py](config.py) 的 `MCPServerConfig.host`/`port` 传给 `FastMCP()`，默认 `127.0.0.1:8000`；`db_path` 字段当前保留未使用，不是隐式数据库选择器。
- host 校验非空；port 范围为 1–65535。不要把配置字段等同于已经实现的环境变量或 transport 切换接口。

## 局部验证

从仓库根运行 `pytest plugins/mcp-server-sqlseed/tests/`；接口回归应断言生成 YAML 内容和真实 SQLite 行数据，而不只核对 mock 调用。

- [test_yaml_execution_validation.py](../../tests/test_yaml_execution_validation.py) 验证错误 YAML 不写入、原始行保持不变，以及有效多表 YAML 仍只执行工具指定表和数量。
- [test_stdio_progress.py](../../tests/test_stdio_progress.py) 用真实 fill 与 stdout 捕获验证进度隔离；不要把直接函数测试描述为已经完成 MCP transport 握手验收。
