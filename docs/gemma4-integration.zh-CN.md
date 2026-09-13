# Gemma 4 集成指南

`sqlseed-ai` 是可选 AI 插件，Gemma 4 是其长期模型后端方向。本文描述 `main`
中的后端配置、结构化响应和独立 AI MCP 入口；安装同一候选包集合的方式见
[升级说明](migration.zh-CN.md)。Core 本身保持离线。

## 项目注册的模型 ID

| 模型 | 变体 | 常用后端格式 | 用途示例 |
|------|------|---------|---------|
| `gemma-4-e2b-it` | E2B (2B Effective, Edge) | Ollama / LM Studio | 超轻量端侧部署 |
| `gemma-4-e4b-it` | E4B (4B Effective, Edge) | LM Studio | 本地 Schema 分析 |
| `gemma-4-12b-it` | 12B Unified | LM Studio / Ollama | 速度与质量均衡 |
| `gemma-4-26b-a4b-it` | 26B A4B MoE | Google AI Studio | 复杂分析 + 自纠正 |
| `gemma-4-31b-it` | 31B Dense | Google AI Studio | Dense 模型选项 |

注册表用于模型 ID 转换和候选选择，不证明当前服务提供该模型，也不表示
每个组合都通过真实模型验收。请以目标服务的模型列表为准并验证小请求。

## 后端配置

### Google AI Studio（云端）

```bash
export SQLSEED_AI_BACKEND=google_ai_studio
export GOOGLE_API_KEY=your-key
# 模型默认使用 gemma-4-26b-a4b-it
```

仅设置 API Key 不会选择 Google 后端。`SQLSEED_AI_BACKEND` 优先于 URL 推断；
未设置后端且 URL 未识别时使用 `openai_compat`，必须指定 `SQLSEED_AI_BASE_URL`。
可用 `SQLSEED_AI_MODEL` 显式选择服务支持的模型。

### LM Studio（本地 GUI）

```bash
export SQLSEED_AI_BACKEND=lm_studio
export SQLSEED_AI_MODEL=google/gemma-4-e4b
# 确保 LM Studio 已运行并加载了 Gemma 4 模型
```

### Ollama（本地 CLI）

```bash
export SQLSEED_AI_BACKEND=ollama
export SQLSEED_AI_MODEL=gemma4:e4b
# 确保 Ollama 已运行：ollama pull gemma4:e4b
```

## 原生函数调用（Native Function Calling）

sqlseed-ai 通过 `GEMMA_TOOLS` 定义了一个函数接口（唯一的工具：`analyze_schema`）：

### analyze_schema

分析数据库表结构，推荐数据生成配置。

```python
GEMMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_schema",
            "description": "Analyze a database table schema and recommend data generation configuration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                    "columns": {"type": "array", "items": {...}},
                    "foreign_keys": {"type": "array", "items": {...}},
                    "indexes": {"type": "array", "items": {...}},
                },
                "required": ["table_name", "columns"],
            },
        },
    }
]
```

### 调用流程

实际策略由 `AIConfig.resolve_tool_calling_protocol()` 按后端解析：

```
1. 仅当解析协议为 "gemma4"（仅 Google AI Studio）或 "openai"
   （Google AI Studio / OpenAI 兼容）时，才尝试原生函数调用
   （tools=GEMMA_TOOLS, tool_choice="auto"）
2. Gemma 4 选择 analyze_schema 函数，返回结构化参数
3. 从 tool_call.function.arguments 中提取 JSON
4. 降级：云端后端（Google AI Studio / OpenAI 兼容）使用 JSON mode
   （response_format: json_object）；本地后端（LM Studio、Ollama）
   直接使用纯文本模式。
```

## 配置校验与修复

单表 `ai-suggest` 的 `AiConfigRefiner` 实现有限次数的自纠正；这不是持久化 Agent 记忆：

```
Gemma 4 生成初始配置
    -> 验证（类型检查、约束检查、依赖完整性）
    -> 如果发现错误：
        -> 将错误信息反馈给 Gemma 4
        -> Gemma 4 修正配置
        -> 重新验证（最多 3 轮）
    -> 返回候选配置供审阅；执行由调用入口决定
```

`ai-analyze` 默认使用 `AutoHealOrchestrator`，`auto-heal` 修复已有 YAML；
它们采用 contract-driven self-healing。详细参数见[CLI 指南](guide.md#cli-reference)。

## MCP 服务器工具

安装兼容的 `sqlseed-ai[mcp]` 后，由独立进程 `mcp-server-sqlseed-ai` 提供
`sqlseed_ai_generate_yaml`，以及下列 3 个 Gemma 4 专用工具。规则型服务器
`mcp-server-sqlseed` 的 2 个工具不会因安装 AI 插件而增加；客户端需分别配置
两个进程。完整 JSON 配置见[MCP 指南](guide.md#mcp-server)。

| 工具 | 说明 |
|------|------|
| `sqlseed_gemma4_analyze` | 使用 Gemma 4 原生函数调用分析 Schema |
| `sqlseed_gemma4_agent_fill` | 端到端 Agent 工作流（分析 -> 配置 -> 填充） |
| `sqlseed_list_gemma_models` | 列出可用的 Gemma 4 模型变体和后端状态 |

## 快速开始

先按照[安装指南](guide.md#installation)安装同一来源的 Core/CLI/AI 包，并准备
数据库及表结构。配置上述一个后端后运行：

```bash
sqlseed ai-suggest app.db -t users -o config.yaml
sqlseed ai-analyze --db app.db -o database-rules.yaml
```

Python 单表分析示例：

```python
from sqlseed_ai import SchemaAnalyzer
from sqlseed_ai.config import AIConfig
from sqlseed.core.orchestrator import DataOrchestrator

config = AIConfig.from_env()
analyzer = SchemaAnalyzer(config=config)

with DataOrchestrator("app.db") as orch:
    schema_ctx = orch.get_schema_context("users")
result = analyzer.analyze_table_from_ctx(**schema_ctx)
```

## 性能与验证

分析耗时取决于硬件、模型、schema 范围、prompt、超时设置和后端负载。
比较前保存这些条件并记录实际结果。固定响应回归证明本地处理逻辑，不能证明
模型可达性或建议质量；本文不提供缺少可追溯实验条件的通用延迟承诺。
