# sqlseed-ai 插件

**源码核验日期：** 2026-09-14

LLM schema 分析、contract-driven self-healing 和模板值生成的独立发行包；依赖方向是本插件 → `sqlseed` / `sqlseed-cli`。Core 必须保持离线，不得反向导入本插件。

## 边界导航

| 工作 | 先读 |
|---|---|
| 运行时代码、backend、协议、contracts / repair / healer | [src/sqlseed_ai/AGENTS.md](src/sqlseed_ai/AGENTS.md) |
| 自动修复协调、跨列 CHECK 推断与最终 YAML 清理 | [src/sqlseed_ai/auto_heal/AGENTS.md](src/sqlseed_ai/auto_heal/AGENTS.md) |
| AI 测试、真实 LLM 环境与 fixtures | [tests/AGENTS.md](tests/AGENTS.md) |

## 发行与入口

- 以 [pyproject.toml](pyproject.toml) 为依赖、extras 和 entry points 的依据；本包直接依赖 `sqlseed`、`sqlseed-cli`、`openai`、`httpx`、`networkx`。
- 当前 AI 要求 Core `>=0.2.4.dev0,<0.3`；Core 0.2.3 缺少 `sqlseed_apply_ai_suggestions` hookspec 和 AI MCP 使用的目标校验函数。
- `[project.entry-points."sqlseed"]` 导出 `ai = "sqlseed_ai:plugin"`；插件实例和 `@hookimpl` 在 [src/sqlseed_ai/__init__.py](src/sqlseed_ai/__init__.py)。
- `[project.entry-points."sqlseed.cli_commands"]` 指向 [src/sqlseed_ai/cli/ai_commands.py](src/sqlseed_ai/cli/ai_commands.py) 的 `register()`；通过注册扩展 CLI，不能让 `sqlseed-cli` 直接依赖 AI 实现。
- `ai-suggest` 默认做单表分析；`ai-suggest --auto-heal`、`ai-analyze` 和 `auto-heal` 使用 v4 `AutoHealOrchestrator` 路径。不要恢复已删除的 `Stage3Validator` / `SchemaSemanticAnalyzer` / `StagedSchemaAnalyzer` 或旧 staged flags。
- [src/sqlseed_ai/mcp.py](src/sqlseed_ai/mcp.py) 提供 AI MCP tools，`mcp-server-sqlseed-ai` 是它的命令入口；运行需要本包 `[mcp]` extra。Core-only MCP 位于兄弟包 `mcp-server-sqlseed`，不要把 LLM 能力搬回那里。
- 修改 AI CLI 的用户行为时，同步 [docs/guide.md](../../docs/guide.md#ai-plugin) 与本包中英文 README 的完整参考；根 [README.md](../../README.md) 与 [README.zh-CN.md](../../README.zh-CN.md) 只保留命令用途概述。
- 修改依赖后同步本包 [uv.lock](uv.lock) 和受影响的根 lock；按根发布流程处理版本、changelog 与其他发行包。

## 配置与兼容性

- 环境配置统一从 `AIConfig.from_env()` 加载；显式传入的 `AIConfig` 保持可用，不在各调用方重复读取环境变量。
- 服务 backend 由 `AIBackend` 表示：Google AI Studio、LM Studio、Ollama 与 OpenAI-compatible。Gemma 4 是长期支持的模型系列，`gemma4` 也是工具调用协议名，不是 `AIBackend` 成员。模型 ID、别名和优先级查 `GemmaModel` / `_model_selector.py`，不要维护重复型号清单。
- backend 解析为显式 `SQLSEED_AI_BACKEND` → 已知 URL 模式 → `OPENAI_COMPAT`；这不是依次探测所有服务的 fallback 链。
- `SQLSEED_AI_API_KEY` 回退到 `GOOGLE_API_KEY` / `OPENAI_API_KEY`；`SQLSEED_AI_BASE_URL` 回退到 `OPENAI_BASE_URL`。其余环境变量与默认值以 [src/sqlseed_ai/config.py](src/sqlseed_ai/config.py) 为准。
- 协议由 `tool_calling_protocol` 和 `resolve_tool_calling_protocol()` 决定，不能仅根据模型名称或 backend 直接选择工具调用路径。

## 本地验证

先按[根指南](../../AGENTS.md#安装与运行)统一安装本地包，再从仓库根执行。仅安装 AI 的独立环境测试 AI MCP 时还需 `[mcp]` extra；测试细分及服务依赖见 [tests/AGENTS.md](tests/AGENTS.md)。

```bash
pytest plugins/sqlseed-ai/tests/
ruff check plugins/sqlseed-ai/
ruff format --check plugins/sqlseed-ai/
mypy plugins/sqlseed-ai/src/sqlseed_ai/
```

涉及包边界时还需按根规范运行 `lint-imports` 和 architecture tests。架构约束以 [ARCHITECTURE.md](../../ARCHITECTURE.md) 为准，通用规则以 [CLAUDE.md](../../CLAUDE.md) 为准；这里仅记录 AI 插件差异。
