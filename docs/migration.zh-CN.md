# 升级到五包工作台

[English](migration.md)

工作台候选版本将原来组合安装的 Core/CLI/MCP 拆分为五个 package。合入 `main` 不会将这些包发布到 PyPI；正式发布前，应使用同一次成功候选 CI 的安装包。

## 成套安装

新建虚拟环境，将同一 CI artifact 中的五个 wheel 一起安装：

```bash
python -m venv .venv
# 使用当前 shell 对应的命令激活虚拟环境。
python -m pip install /path/to/candidate-wheels/*.whl
python -m pip check
```

从源码安装时，在同一次依赖解析中提供 Core 和本地插件：

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e './plugins/sqlseed-ai[mcp]' -e ./plugins/mcp-server-sqlseed -e ./plugins/sqlseed-web
python -m pip check
```

候选插件要求 Core `>=0.2.4.dev0,<0.3`，CLI/AI 兄弟包依赖也限制在相同版本系列。Core 0.2.3 缺少新插件使用的接口。上界避免自动选择尚未经兼容审查的新 minor 版本，但不保证区间内任意开发快照都能混用；仍应成套安装。

CI run 的 `headSha` 标识候选源码。PR artifact 名称可能使用 GitHub 的临时合并提交，因此需要同时核对 run 与 artifact。升级验证完成前保留原环境和原安装包。

## 调整入口

| 原有用法 | 新入口 |
| --- | --- |
| Python `from sqlseed import fill, connect, preview` | 仍属于 Core，保留既有 public API |
| 安装 Core 后直接使用 `sqlseed` 命令 | 安装 `sqlseed-cli`；正式发布后也可用 `sqlseed[cli]` convenience extra |
| 导入 `sqlseed.cli` | 改用 CLI package 提供的命令入口；旧 Core 模块已删除 |
| Core MCP 同时提供 AI 工具 | 单独运行 `sqlseed-ai[mcp]` 提供的 `mcp-server-sqlseed-ai` |
| 浏览器工作流程 | 运行 `sqlseed-web`，打开 `http://127.0.0.1:8630` |

`mcp-server-sqlseed` 现提供离线规则生成 `sqlseed_generate_yaml(db_path, table_name)` 和执行工具 `sqlseed_execute_fill`。旧 `sqlseed_generate_yaml` 的 AI 参数、schema inspection 工具和 schema resource 已删除，需要更新 MCP 客户端的工具选择和保存的调用。

AI server 提供 `sqlseed_ai_generate_yaml`、`sqlseed_gemma4_analyze`、`sqlseed_gemma4_agent_fill`、`sqlseed_list_gemma_models`。需要单独配置 backend；MCP server 启动成功不代表真实模型可达，接入自动流程前先验证一个小请求。

## 验证旧配置与数据

先用新的测试数据库或可丢弃的副本。除 `GenerationResult.errors` 和 `count` 外，还应检查实际存储值。Core 普通分批模式下，后续失败可能保留先前已提交批次，不能仅凭函数正常返回判断全部成功。详见[支持与维护约定](maintainable-release.md)。

从 SQLite 原有无类型绑定写入路径迁移时，重点复核 JSON 与日期时间字段。JSON generator 返回序列化 JSON 文本，写入 JSON 列后应保留 object/array/scalar 语义；普通 TEXT 列仍按文本处理。日期时间列使用明确的 ISO 值或对应 Python date/time 对象；非法值会报告错误，不静默修复。

JSON 字符串值应提供 `"hello"` 这样的序列化文档，包含 JSON 引号；裸字符串 `hello` 不是合法 JSON。序列化的 `null` 表示 JSON null，SQLAlchemy 显式 `null()` 保留 SQL NULL 语义，也支持 Python 原生对象。SQLite 原样保留合法 JSON 文本，避免格式变化破坏按文本比较的外键；内部 JSON 采样和 lookup 同样保留序列化文档约定。日期时间绑定遵循数据库列类型，SQLite 日期时间列经 SQLAlchemy 写入时不保留时区偏移；需要精确保留原始时间戳文本时使用 TEXT 列。

自引用表带复合主键或 UNIQUE 时，用实际外键和唯一性查询核对结果。不需要父引用时保留显式全 NULL 规则。可空根节点是合法结果，并不保证每行都分配父节点。

Web 是没有多用户认证的本地工作台。PostgreSQL 支持有明确边界，包括当前不支持的复合/跨 schema 外键生成。迁移复杂结构或向其他用户开放服务前，先核对支持约定。

## 合并与发布

公开文档仅在 main 的全部 CI 任务成功后部署，并构建同一提交。部署失败时重跑对应 main CI run；独立 Pages workflow 不再保留可绕过这些检查的 push/manual 触发入口。

PyPI 发布仍是独立操作，要求版本 tag 和五包版本一致。PR 已合并、文档站已更新，都不表示已发布新的 Python 包。
