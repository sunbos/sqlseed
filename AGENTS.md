# AGENTS.md — sqlseed

## 项目目的

- `sqlseed` 是一个声明式 SQLite 测试数据生成工具包，主入口包括 Python API、Click CLI、pluggy 插件体系，以及两个可选子包：`sqlseed-ai` 和 `mcp-server-sqlseed`。
- 优先在现有架构内演进。除非任务明确要求，不要重排公开 API、插件协议、包边界或配置格式。

## 顶层结构

- `src/sqlseed/`：主包。公共 API、CLI、编排、生成器、数据库适配器、配置与 hook 规范都在这里。
- `plugins/sqlseed-ai/`：可选 AI 插件包，通过 `sqlseed` entry point 接入。
- `plugins/mcp-server-sqlseed/`：可选 MCP 服务器包，封装 FastMCP 工具与资源。
- `tests/`：单元、集成、插件与基准测试。
- `docs/`：文档与计划，不是运行时代码。

## 子级 AGENTS

- `src/sqlseed/AGENTS.md`
- `src/sqlseed/core/AGENTS.md`
- `plugins/sqlseed-ai/AGENTS.md`
- `plugins/mcp-server-sqlseed/AGENTS.md`
- `tests/AGENTS.md`

进入这些目录工作时，优先读取最近的子级 `AGENTS.md`，只把根级规则当作全局补充。

## 常见落点

- 改公共 API：`src/sqlseed/__init__.py`
- 改 CLI：`src/sqlseed/cli/main.py`
- 改核心编排、推断、约束、SharedPool：`src/sqlseed/core/`
- 改 Provider、Registry、流式生成：`src/sqlseed/generators/`
- 改 SQLite 适配器与 PRAGMA 优化：`src/sqlseed/database/`
- 改配置模型、加载与快照：`src/sqlseed/config/`
- 改 hook 规范或插件管理：`src/sqlseed/plugins/`
- 改 AI 建议与自纠正：`plugins/sqlseed-ai/`
- 改 MCP 工具或资源：`plugins/mcp-server-sqlseed/`
- 补测试：`tests/`

## 全局规则

- 目标版本是 Python 3.10+。保留 `from __future__ import annotations`，并为新增或修改的函数写完整类型注解。
- 公共函数默认使用仅关键字参数；已知例外是 `generate_choice(choices)`，不要把它误改成仅关键字接口。
- 结构化日志统一走 `sqlseed._utils.logger.get_logger(__name__)`。
- 处理 SQL 标识符时始终使用 `sqlseed._utils.sql_safe.quote_identifier()`；不要对表名、列名或用户值拼 f-string SQL。
- 保持可选依赖可选：核心包不能因为 `faker`、`mimesis`、`openai` 或 `mcp` 缺失而无法导入。
- 需要随机性时优先复用 Provider 自带 RNG 或局部 RNG，不要引入新的模块级全局随机状态。
- `pluggy` 的项目名固定为 `sqlseed`；外部插件通过 `[project.entry-points."sqlseed"]` 发现。
- 公开行为变化必须配套测试更新。这个仓库默认跑覆盖率，回归很容易在 `pytest` 中暴露。
- 如果你因为架构变化更新了根级 agent 文档，也检查 `CLAUDE.md` 和 `GEMINI.md` 是否已经过时。

## 构建与验证

- 安装主包开发环境：`pip install -e ".[dev,all]"`
- 安装 AI 插件：`pip install -e "./plugins/sqlseed-ai"`
- 安装 MCP 插件：`pip install -e "./plugins/mcp-server-sqlseed"`
- Lint：`ruff check src/ tests/`
- 格式检查：`ruff format --check src/ tests/`
- 类型检查：`mypy`
- 全量测试：`pytest`

## 评审重点

- 公开 API、CLI 参数、配置模型和 hook 签名都属于外部契约，改动前先查对应测试与 README。
- 核心编排代码有不少“软失败”路径：Provider 回退、AI 建议缺席、批量 transform 链式透传、异常转 `GenerationResult.errors`。如果要改成硬失败，必须同步更新测试与文档。
- 插件包是独立分发单元。不要把插件实现细节反向塞回主包导入路径里。
