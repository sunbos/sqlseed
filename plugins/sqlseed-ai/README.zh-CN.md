# sqlseed-ai

[English](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/README.md) |
**[中文](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/README.zh-CN.md)**

[sqlseed](https://sunbos.github.io/sqlseed/) 的可选 LLM Schema 分析与契约驱动配置修复插件。
提供列规则建议、配置校验与修复，以及模板候选值生成。接受的配置可交由 Core 离线执行。

支持 Google AI Studio、LM Studio、Ollama 和 OpenAI-compatible API 后端。
安装插件不会验证模型可达性或建议质量；这些需要使用实际后端单独测试。

## 安装

安装 0.2.4 版本时，使用 Python 3.10+ 虚拟环境：

```bash
python -m pip install "sqlseed-ai==0.2.4"
```

Core 0.2.3 缺少本插件使用的 hooks 与数据库目标校验接口。
开发源码时，从仓库根一次安装本地 Core、CLI 和 AI：

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e ./plugins/sqlseed-ai
```

## CLI 快速开始

先配置后端、该服务可用的模型，以及服务要求的凭据。例如 OpenAI-compatible 服务：

```bash
export SQLSEED_AI_BACKEND=openai_compat
export SQLSEED_AI_BASE_URL="https://your-service.example/v1"
export SQLSEED_AI_MODEL="your-available-model"
export SQLSEED_AI_API_KEY="your-api-key"
```

使用 Google AI Studio 时显式选择 `SQLSEED_AI_BACKEND=google_ai_studio`，
并设置服务所需 API Key；只设置 `GOOGLE_API_KEY` 不会选择 Google 后端。
本地无认证服务通常不需要真实 API Key。

分析前应已创建 SQLite 数据库与目标表：

```bash
# 单表分析并校验建议配置；verify 默认开启，最多重试 3 次
sqlseed ai-suggest app.db --table users --output users.yaml --verify --no-cache

# 使用 v4 AutoHealOrchestrator 分析全库
sqlseed ai-analyze --db app.db --output config.yaml

# 通过 URL 分析 PostgreSQL；需在该环境安装 Core 的 postgres extra
sqlseed ai-analyze --url "postgresql+psycopg://user:pass@host/db" -o config.yaml

# 保存完整 LLM 交互用于诊断
sqlseed ai-analyze --db app.db -o config.yaml --log-llm

# 修复已有 YAML 配置
sqlseed auto-heal --db app.db --config broken.yaml --output healed.yaml

# 审阅生成规则后离线执行
sqlseed fill --config users.yaml --no-ai
```

本插件为 CLI 增加三个命令：

| 命令 | 行为 |
| --- | --- |
| `ai-suggest` | 单表 LLM 分析与可选自纠正；`--auto-heal` 选择 AutoHeal 路径 |
| `ai-analyze` | 全库或指定表分析，支持依赖范围与配置合并 |
| `auto-heal` | 修复输入 YAML，保留表范围、行数、seed 和未受影响的规则 |

`ai-analyze --tables orders` 默认包含最多 `--max-depth 5` 层引用的父表。
使用 `--no-dependencies` 或 `--max-depth 0` 仅分析指定表。未知表名在写文件前报错。
`--merge` 必须提供 `--output`：只替换显式选中的表，保留已有依赖表、无关表和全局设置，
并追加尚不存在的生成表。

`auto-heal --config` 实际读取并修复该文件。必须指定 `--db` 或 `--url` 之一，
两者互斥并决定输出连接。YAML、配置结构错误或输入含未知表时，不覆盖输出文件。

接受模型修复前，healer 校验配置结构、内置 generator 名称、参数名及参数注解类型，
再运行既有 contract validator。无效候选进入确定性降级。正常预览和执行仍不可省略：
native/custom 方法、实际生成值及依赖数据库状态的约束需另行验证。

三个命令均不接受 `--backend`；使用环境变量或识别到的 Base URL 选择后端。
`ai-suggest` 支持 `--verify/--no-verify`、`--max-retries`、`--no-cache`、`--timeout`；
`ai-analyze` 的 `--max-retries` 默认是 `2`，`auto-heal` 默认是 `3`。
具体参数以 `sqlseed <command> --help` 为准。

## 独立 AI MCP 服务器

AI MCP 入口要求本包的 `mcp` extra：

```bash
python -m pip install "sqlseed-ai[mcp]==0.2.4"
mcp-server-sqlseed-ai
```

开发源码时使用 `python -m pip install -e . -e ./plugins/sqlseed-cli -e "./plugins/sqlseed-ai[mcp]"`。
配置 MCP 客户端启动 `mcp-server-sqlseed-ai`，它提供四个工具：

- `sqlseed_ai_generate_yaml`
- `sqlseed_gemma4_analyze`
- `sqlseed_gemma4_agent_fill`
- `sqlseed_list_gemma_models`

无需 LLM 的规则生成和数据填充由独立的
[Core MCP 包](https://github.com/sunbos/sqlseed/tree/main/plugins/mcp-server-sqlseed)提供。
安装 AI 不会向 `mcp-server-sqlseed` 进程注入这些工具，客户端须分别配置两个进程。
工具发现或成功获取模型列表，不等于模型推理已经可用。

## 配置与模型选择

环境配置统一通过 `AIConfig.from_env()` 加载；也可以显式构造 `AIConfig`。
后端解析顺序是显式 `SQLSEED_AI_BACKEND`、已知 URL 模式、最后 `openai_compat`。
这不是逐个探测所有服务的 fallback 链。

| 变量 | 用途 |
| --- | --- |
| `SQLSEED_AI_BACKEND` | `google_ai_studio`、`lm_studio`、`ollama` 或 `openai_compat` |
| `SQLSEED_AI_BASE_URL` | 服务端点；回退到 `OPENAI_BASE_URL` |
| `SQLSEED_AI_MODEL` | 所选服务提供的模型 ID |
| `SQLSEED_AI_API_KEY` | 服务凭据；依次回退到 `GOOGLE_API_KEY`、`OPENAI_API_KEY` |
| `SQLSEED_AI_TOOL_CALLING_PROTOCOL` | 请求使用 `gemma4`、`openai` 或 `none` 协议，按后端支持情况解析 |
| `SQLSEED_AI_TIMEOUT` | 请求超时秒数；`0` 按后端和模型选择 |
| `SQLSEED_CACHE_DIR` | 覆盖平台默认 sqlseed 缓存目录 |

`openai_compat` 必须配置 Base URL。其他后端默认地址如下：

| 后端 | 默认 Base URL |
| --- | --- |
| Google AI Studio | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| LM Studio | `http://127.0.0.1:1234/v1` |
| Ollama | `http://localhost:11434/v1` |

显式 `--model` 或 `SQLSEED_AI_MODEL` 优先。未指定模型时，LM Studio/Ollama
尝试检测已加载模型，再使用本地 Gemma E4B 回退 ID；云端按后端格式选择项目注册的
Gemma 26B ID。注册的模型名称不保证服务当前提供该模型，请查询服务实际列表并验证。
模型 ID、别名和后端映射以
[配置源码](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/src/sqlseed_ai/config.py)为准。

自动超时为云端 60 秒、本地普通模型 120 秒、本地 reasoning 模型 300 秒。
显式正数超时会保留至少 30 秒。模型配置和已安装状态均不能代替实际请求测试。

## 分析、修复与模板池

`SchemaAnalyzer` 使用列、索引、样本数据、外键和数据分布构建 Prompt，返回列级配置。
单表 `ai-suggest` 的 `AiConfigRefiner` 校验配置与实际 schema，遇到可修复错误时请求模型
修正；默认最多重试 3 次，仍失败时报告 `AISuggestionFailedError`。
`ai-analyze` 和 `auto-heal` 则使用 v4 `AutoHealOrchestrator` 的契约驱动路径。

开启 AI 生成路径时，`sqlseed_pre_generate_templates` 可为符合条件的未匹配字符串列
准备候选值。用户明确配置、UNIQUE、默认值或主键等条件会影响是否使用模板池，
不保证每个复杂字段都会调用模型。

### 工具调用协议

`tool_calling_protocol` 与 `resolve_tool_calling_protocol()` 一起决定响应协议，
不能只根据模型名称决定。`gemma4` 仅在 Google AI Studio 解析为工具调用，
`openai` 支持 Google AI Studio 与 OpenAI-compatible；LM Studio/Ollama 使用无工具协议。

工具调用路径发送 `tools=GEMMA_TOOLS` 和 `tool_choice="auto"`，从响应中提取
`analyze_schema` 的参数或解析文本。它不是强制返回函数调用；不支持工具调用时，
云端回退 JSON mode，本地使用 text mode。结构化响应仍需校验，不能保证模型输出正确。

### 文件缓存

AI 配置缓存包含 schema hash，结构变化会使旧建议失效；`--no-cache` 跳过缓存。
默认路径为 macOS 的 `~/Library/Caches/sqlseed/ai_configs/`、Linux 的
`$XDG_CACHE_HOME/sqlseed/ai_configs/`（未设置时为 `~/.cache/sqlseed/ai_configs/`），
以及 Windows 的 `%LOCALAPPDATA%/sqlseed/ai_configs/`。
`SQLSEED_CACHE_DIR` 可覆盖缓存根目录。写入数据前仍需审阅模型输出。

## 插件 Hooks

本插件通过 `[project.entry-points."sqlseed"]` 注册实例，实现：

| Hook | 用途 |
| --- | --- |
| `sqlseed_ai_analyze_table` | LLM 表分析，返回列配置 |
| `sqlseed_apply_ai_suggestions` | 编排器使用的高层 AI 中介入口，判断是否需要分析并合并结果 |
| `sqlseed_transform_row` | 实现 DATE 字符串转换，但普通 Core 生成不调用此 hook，不能依赖它修复写入类型 |
| `sqlseed_pre_generate_templates` | 为符合条件的列准备候选值 |

CLI 命令另由 `sqlseed.cli_commands` entry point 注册。本插件不实现 provider 或
column-mapper 注册 hooks，也不要求 Core 导入 AI 实现。

## 依赖

- Python `>=3.10`
- `sqlseed>=0.2.4.dev0,<0.3`
- `sqlseed-cli>=0.2.4.dev0,<0.3`
- `openai>=1.0`
- `httpx>=0.24.0`
- `networkx>=3.0`
- 可选 `mcp` extra：`mcp>=1.0,<2`
- 实际模型请求需要已配置且可达的后端

更多信息见[AI 集成指南](https://sunbos.github.io/sqlseed/gemma4-integration.zh-CN/)、
[升级说明](https://sunbos.github.io/sqlseed/migration.zh-CN/)和
[配置源码](https://github.com/sunbos/sqlseed/blob/main/plugins/sqlseed-ai/src/sqlseed_ai/config.py)。

许可证：[AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE)。
发行包包含完整 LICENSE 文本。
